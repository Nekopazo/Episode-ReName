import argparse
import os
import platform
import re
import sys
import time
from datetime import datetime

from custom_rules import starts_with_rules
from utils.config_utils import get_qrm_config
from utils.ep_utils import ep_format
from utils.ext_utils import COMPOUND_EXTS, get_file_name_ext, fix_ext
from utils.file_name_utils import clean_name, zero_fix, name_format_bypass_check
from utils.log_utils import logger
from utils.path_utils import (
    format_path,
    get_absolute_path,
    delete_empty_dirs,
    check_and_delete_redundant_file,
)
from utils.resolution_utils import get_resolution_in_name, resolution_dict
from utils.season_utils import get_season_cascaded, get_season, get_season_path
from utils.series_utils import get_series_from_season_path

# print('''
#     -- 警告 --
#     如果用这个程序导致文件乱了后果自负哈哈哈哈哈哈哈
#
#     -- 运行环境 --
#     需要python3环境 不推荐使用群晖的python3.5套件环境,可能出现部分字符不兼容
#     -- 使用方法 --
#     1.命令行运行
#     python3 rename.py "/path/to/folder"
#     2.直接运行
#     修改 target_path的路径
#     python3 rename.py
#     -- 程序原理 --
#     优先解析括号
#     [] 【】()内的1-4位纯数字优先
#     部分特殊处理
#     括号没有
#     取剩余部分结尾的数字
#     部分特殊处理
#     应该能解析出大部分的命名规则了
# ''')

script_path = os.path.dirname(os.path.realpath(__file__))
target_path = ''

# 重命名的文件移动到season目录下
move_up_to_season_folder = True

# pyinstaller打包后, 通过命令行调用, 必须这样才能获取到exe文件路径, 普通的script_path获取的是临时文件路径
# 拿到这个路径之后才能方便地读取到exe同目录的文件
if getattr(sys, 'frozen', False):
    application_path = os.path.dirname(os.path.realpath(sys.executable))
elif __file__:
    application_path = os.path.dirname(os.path.realpath(__file__))


# if len(sys.argv) < 2:
#     exit()

# 默认配置
rename_delay = 0
rename_overwrite = True

# logger.add(os.path.join(application_path, 'app.log'))
# logger.info(sys.argv)
# print(sys.argv)

# # 测试
# if not getattr(sys, 'frozen', False) and len(sys.argv) == 1:
#     # 直接运行的目标路径
#     # sys.argv.append(r'\\DSM\DSM_share5\season1\aaa E02 AAA.mp4')
#     # sys.argv.append(r'\\DSM\DSM_share5\season1')
#     # sys.argv.append(r'E:\test\极端试验样本\s01\极端试验样本 - S01E01.mp4')
#     # sys.argv.append(r'E:\test\极端试验样本\s01\S01E01 - 720p.mp4')
#     sys.argv.append(r'E:\test\极端试验样本\s01')

if len(sys.argv) > 1 and not sys.argv[1].startswith('-'):
    # 旧版的命令解析
    # 简单通过判断是否有 - 来区分新旧参数
    # python EpisodeReName.py E:\test\极端试验样本\S1

    # 读取命令行目标路径
    target_path = sys.argv[1]
    logger.info(f"{'target_path', target_path}")
    if len(sys.argv) > 2:
        # 重命名延迟(秒) 配合qb使用的参数, 默认为0秒
        rename_delay = int(sys.argv[2])
        logger.info(f"{'rename_delay', rename_delay}")
    name_format = 'S{season}E{ep}'
    # name_format = '{series} - S{season}E{ep}'
    # name_format = 'S{season}E{ep} - {resolution}'
    name_format_bypass = True
    force_rename = 0
    custom_replace_pair = ""
    use_folder_as_season = 0
    del_empty_folder = 0
    priority_match = 0
else:
    # 新的argparse解析
    # python EpisodeReName.py --path E:\test\极端试验样本\S1 --delay 1 --overwrite 1
    # python EpisodeReName.py --path E:\test\极端试验样本\S1 --delay 1 --overwrite 0
    # EpisodeReName.exe --path E:\test\极端试验样本\S1 --delay 1 --overwrite 0
    # python EpisodeReName.py --path /home/nate/data/极端试验样本/s1/ --delay 1 --overwrite 1 --name_format "S{season}E{ep} - {resolution}"

    ap = argparse.ArgumentParser()
    ap.add_argument('--path', required=True, help='目标路径')
    ap.add_argument(
        '--delay', required=False, help='重命名延迟(秒) 配合qb使用的参数, 默认为0秒不等待', type=int, default=0
    )
    ap.add_argument(
        '--overwrite',
        required=False,
        help='强制重命名, 默认为1开启覆盖模式, 0为不覆盖, 遇到同名文件会跳过, 结果输出到error.txt',
        type=int,
        default=1,
    )
    ap.add_argument(
        '--name_format',
        required=False,
        help='(慎用) 自定义重命名格式, 参数需要加引号 默认为 "S{season}E{ep}" 可以选择性加入 系列名称如 "{series} - S{season}E{ep}" ',
        default='S{season}E{ep}',
    )
    ap.add_argument(
        '--name_format_bypass', required=False, help='(慎用) 自定义重命名格式, 对满足格式的文件忽略重命名步骤', default=0
    )
    ap.add_argument(
        '--parse_resolution',
        required=False,
        help='(慎用) 识别分辨率，输出结果类似于 `S01E01 - 1080p.mp4`, 1为开启, 0为不开启. 开启后传入的 name_format 参数会失效, 强制设置为 "S{season}E{ep} - {resolution}"',
        default=0,
    )
    ap.add_argument(
        '--force_rename',
        required=False,
        help='(慎用) 即使已经是标准命名, 也强制重新改名, 默认为0不开启, 1是开启',
        type=int,
        default=0,
    )
    ap.add_argument(
        '--replace',
        required=False,
        type=str,
        nargs='+',
        action='append',
        help='自定义替换关键字, 一般是给字幕用, 用法 `--replace chs chi --replace cht chi` 就能把chs和cht替换成chi, 可以写多组关键字',
        default=[],
    )
    ap.add_argument(
        '--use_folder_as_season',
        required=False,
        help='优先使用父级文件夹中的季数来代替文件名中的季数, 默认为0不开启, 1是开启',
        type=int,
        default=0,
    )
    ap.add_argument(
        '--del_empty_folder',
        required=False,
        help='删除空的子目录, 默认为0不开启, 1是开启',
        type=int,
        default=0,
    )
    ap.add_argument(
        '--priority_match',
        required=False,
        help='(慎用) 目标文件如果存在，会导致覆盖操作的时候，优先保留满足第一组匹配规则的文件，如果新文件不满足匹配，则删除新文件。默认为0不开启, 1是开启',
        type=int,
        default=0,
    )

    args = vars(ap.parse_args())
    target_path = args['path']
    rename_delay = args['delay']
    rename_overwrite = args['overwrite']
    name_format = args['name_format']
    name_format_bypass = args['name_format_bypass']
    parse_resolution = args['parse_resolution']
    force_rename = args['force_rename']
    custom_replace_pair = args['replace']
    use_folder_as_season = args['use_folder_as_season']
    del_empty_folder = args['del_empty_folder']
    priority_match = args['priority_match']

    if parse_resolution:
        name_format = 'S{season}E{ep} - {resolution}'

if not target_path:
    # 没有路径参数直接退出
    sys.exit()

# 除samba格式的路径外 其它格式的路径斜杠统一处理
if not target_path.startswith(r'\\'):
    target_path = target_path.replace('\\', '/').replace('//', '/')

# 忽略字符串, 用于处理剧集名字中带数字的文件, 提取信息时忽略这些字符串
# ignore 文件必须用utf-8编码
ignores = [
    "[VCB-Studio]", "[ANK-Raws]",  # 原有忽略词
    "h264", "x264", "h265", "x265", "flac", "1080", "720"  # 新增技术参数
]
ignore_file = os.path.join(application_path, 'ignore')
if os.path.exists(ignore_file):
    with open(ignore_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and line not in ignores:
                ignores.append(line)


# 输出结果列表
file_lists = []
unknown = []

# 当前系统类型
system = platform.system()


def get_season_and_ep(file_path):
    logger.info(f"{'解析文件', file_path}")

    # 去掉ignore文件中忽略的字符串，防止解析错误
    for x in ignores:
        file_path = file_path.replace(x, '')

    season = None
    ep = None

    file_full_name = os.path.basename(file_path)

    # 父级文件夹
    parent_folder_path = os.path.dirname(file_path)

    # 获取文件名和后缀
    file_name, ext = get_file_name_ext(file_full_name)

    _ = get_season_cascaded(parent_folder_path)
    if not _:
        # logger.info(f"{'不在season文件夹内 忽略'}")
        return None, None

    # 忽略已按规则命名的文件
    pat = 'S(\d{1,4})E(\d{1,4}(\.5)?)'
    res = re.match(pat, file_name)
    if res:
        logger.info(f"{'忽略识别: 已按规则命名'}")
        if force_rename:
            season, ep = res[1], res[2]
            season = str(int(season)).zfill(2)
            ep = ep_format(ep)
            return season, ep
        else:
            return None, None

    # 如果文件已经有 S01EP01 或者 S01E01 直接读取
    pat = '[Ss](\d{1,4})[Ee](\d{1,4}(\.5)?)'
    res = re.findall(pat, file_name.upper())
    if res:
        season, ep = res[0][0], res[0][1]
        season = str(int(season)).zfill(2)
        ep = ep_format(ep)
        return season, ep
    pat = '[Ss](\d{1,4})[Ee][Pp](\d{1,4}(\.5)?)'
    res = re.findall(pat, file_name.upper())
    if res:
        season, ep = res[0][0], res[0][1]
        season = str(int(season)).zfill(2)
        ep = ep_format(ep)
        return season, ep

    season = get_season_cascaded(parent_folder_path)

    # 获取不到季数 退出
    if not season:
        return None, None

    # 根据文件名获取集数

    # 特殊文件名使用配置的匹配规则
    # 确定是否满足特殊规则
    use_custom_rule = False
    for starts_str, rules in starts_with_rules:
        if file_name.startswith(starts_str):
            use_custom_rule = True
            for rule in rules:
                try:
                    res = re.findall(rule, file_name)
                    if res:
                        logger.info(f"{'根据特殊规则找到了集数'}")
                        ep = res[0]
                        season = str(int(season)).zfill(2)
                        ep = ep_format(ep)
                        return season, ep
                except Exception as e:
                    logger.info(f'{e}')
    # 如果满足特殊规则还没找到ep 直接返回空
    if use_custom_rule and not ep:
        return None, None

    # 其它不在特殊规则的继续往下正常查找匹配

    # 常见的括号
    bracket_pairs = [
        ['\[', '\]'],
        ['\(', '\)'],
        ['【', '】'],
        # 日语括号
        ['「', '」'],
    ]
    # 内容
    patterns = [
        # 1到4位数字
        '(\d{1,4}(\.5)?)',
        # 特殊文字处理
        '第(\d{1,4}(\.5)?)集',
        '第(\d{1,4}(\.5)?)话',
        '第(\d{1,4}(\.5)?)話',
        '[Ee][Pp](\d{1,4}(\.5)?)',
        '[Ee](\d{1,4}(\.5)?)',
        # 兼容SP01等命名
        '[Ss][Pp](\d{1,4}(\.5)?)',
        # 兼容v2命名
        '(\d{1,4}(\.5)?)[Vv]?\d?',
        # 兼容END命名
        '(\d{1,4}(\.5)?)\s?(?:_)?(?i:END)?',
    ]
    # 括号和内容组合起来
    pats = []
    for pattern in patterns:
        for bracket_pair in bracket_pairs:
            pats.append(bracket_pair[0] + pattern + bracket_pair[1])
    # 查找
    for pat in pats:
        res = re.search(pat, file_name)
        if res:
            ep = res.group(1)
            break

    if not ep:
        logger.info(f"{'括号内未识别, 开始寻找括号外内容'}")
        # 把括号当分隔符排除掉括号内的文字
        pat = ''
        for bracket_pair in bracket_pairs:
            pat += bracket_pair[0] + '.*?' + bracket_pair[1] + '|'
        pat = pat[:-1]
        # 兼容某些用 - 分隔的文件
        pat += '|\-|\_'
        logger.info(f'pat {pat}')
        res = re.split(pat, file_name)
        # 过滤空字符串
        res = list(filter(None, res))
        # 从后向前查找数字, 一般集数在剧集名称后面, 防止剧集有数字导致解析出问题
        res = res[::-1]

        # logger.info(f'{res}')

        if not ep:
            # 部分资源命名
            # 找 第x集
            pat = '第(\d{1,4}(\.5)?)[集话話]'
            for y in res:
                y = y.strip()
                res_sub = re.search(pat, y)
                if res_sub:
                    ep = res_sub.group(1)
                    break
        if not ep:
            # 找 EPXX
            pat = '[Ee][Pp](\d{1,4}(\.5)?)'
            for y in res:
                y = y.strip()
                res_sub = re.search(pat, y.upper())
                if res_sub:
                    ep = res_sub.group(1)
                    break

        # 特殊命名 SExx.xx 第2季第10集 SE02.10
        if not ep:
            # logger.info(f"{'找 EXX'}")
            pat = '[Ss][Ee](\d{1,2})\.(\d{1,2})'
            for y in res:
                y = y.strip()
                res_sub = re.search(pat, y.upper())
                if res_sub:
                    season = res_sub.group(1)
                    ep = res_sub.group(2)
                    break

        # 特殊命名 Sxx.xx 第2季第10集 s02.10
        if not ep:
            # logger.info(f"{'找 EXX'}")
            pat = '[Ss](\d{1,2})\.(\d{1,2})'
            for y in res:
                y = y.strip()
                res_sub = re.search(pat, y.upper())
                if res_sub:
                    season = res_sub.group(1)
                    ep = res_sub.group(2)
                    break

        # 匹配顺序调整
        if not ep:
            # logger.info(f"{'找 EXX'}")
            pat = '[Ee](\d{1,4}(\.5)?)'
            for y in res:
                y = y.strip()
                res_sub = re.search(pat, y.upper())
                if res_sub:
                    ep = res_sub.group(1)
                    break

        def extract_ending_ep(s):
            logger.info(f"{'找末尾是数字的子字符串'}")
            s = s.strip()
            # logger.info(f'{s}')
            ep = None

            # 兼容v2和.5格式 不兼容 9.33 格式
            # 12.5
            # 13.5
            # 10v2
            # 10.5v2
            pat = '(\d{1,4}(\.5)?)[Vv]?\d?'
            ep = None
            res_sub = re.search(pat, s)
            if res_sub:
                logger.info(f'{res_sub}')
                ep = res_sub.group(1)
                return ep

            # 兼容END命名
            pat = '(\d{1,4}(\.5)?)\s?(?:_)?(?i:END)?'
            ep = None
            res_sub = re.search(pat, s)
            if res_sub:
                logger.info(f'{res_sub}')
                ep = res_sub.group(1)
                return ep

            pat = '\d{1,4}(\.5)?$'
            res_sub = re.search(pat, s)
            if res_sub:
                logger.info(f'{res_sub}')
                ep = res_sub.group(0)
                return ep
            return ep

        if not ep:
            for s in res:
                ep = extract_ending_ep(s)
                if ep:
                    break

    season = zero_fix(season)
    ep = zero_fix(ep)

    return season, ep


def ep_offset_patch(file_path, ep):
    # 多季集数修正
    # 20220721 修改集数修正修正规则：可以用 + - 符号标记修正数值, 表达更直观
    b = os.path.dirname(file_path.replace('\\', '/'))
    offset_str = None
    while b:
        if offset_str:
            break
        if not '/' in b:
            break
        b, fo = b.rsplit('/', 1)
        offset_str = None
        if get_season(fo):
            try:
                for fn in os.listdir(b + '/' + fo):
                    if fn.lower() != 'all.txt':
                        continue
                    with open(b + '/' + fo + '/' + fn, encoding='utf-8') as f:
                        offset_str = f.read()
                        break
            except Exception as e:
                logger.info(f"{'集数修正报错了', e}")
                return ep
    # 没有找到all.txt 尝试寻找qb-rss-manager的配置文件
    # 1. config_ern.json 配置
    # 2. 这两个exe在同一个目录下, 直接读取配置
    if not offset_str:
        qrm_config = get_qrm_config(application_path)

        if qrm_config:
            # logger.info(f"{'qrm_config', qrm_config}")
            # logger.info(f"{'file_path', file_path}")
            season_path = get_season_path(file_path)
            # logger.info(f"{'season_path', season_path}")
            if 'data_list' in qrm_config:
                logger.info('检测到 qb-rss-manager 的 旧版 格式数据')
                for x in qrm_config['data_list']:
                    if format_path(x[5]) == format_path(season_path):
                        if x[4]:
                            try:
                                offset_str = x[4]
                                logger.info(f"{'QRM获取到 offset_str', offset_str}")
                            except:
                                pass
            else:
                logger.info('检测到 qb-rss-manager 的 v1 格式数据')
                for data_group in qrm_config['data_dump']['data_groups']:
                    for x in data_group['data']:
                        if format_path(x['savePath']) == format_path(season_path):
                            if x['rename_offset']:
                                try:
                                    offset_str = x['rename_offset']
                                    logger.info(f"{'QRM获取到 offset_str', offset_str}")
                                except:
                                    pass
    # 集数修正
    if offset_str:
        try:
            offset_str = offset_str.strip().replace(' ', '')
            if '|' not in offset_str:
                logger.info('单一数字类型的offset')
                # 直接取整数, 正数为减少, 负数是增加
                offset = int(offset_str)
            else:
                logger.info('多组数据的offset解析')
                # 和 QRM 多组匹配对应的多组offset
                # 比如: 格式 `12|0|-11` 第一组集数减12, 第二组不变, 第三组加11

                if not qrm_config:
                    logger.info('未获取到QRM的配置，默认取第一个offset')
                    offset = int(offset_str.sptit('|')[0].strip())
                else:
                    # 查找QRM配置匹配的组序号
                    index = 0
                    for data_group in qrm_config['data_dump']['data_groups']:
                        for x in data_group['data']:
                            if format_path(x['savePath']) == format_path(season_path):
                                try:
                                    must_contain_tmp = x['mustContain']
                                    if '|' not in must_contain_tmp:
                                        break
                                    else:
                                        for i, keywords in enumerate(must_contain_tmp.split('|')):
                                            if all(
                                                [
                                                    keyword.strip() in file_path
                                                    for keyword in keywords.strip().split(' ')
                                                ]
                                            ):
                                                index = i
                                                break
                                except:
                                    pass
                    # 获取offset
                    offset = int(offset_str.split('|')[index].strip())
                    logger.info(f'解析offset {offset}')

            if '.' in ep:
                ep_int, ep_tail = ep.split('.')
                ep_int = int(ep_int)
                if int(ep_int) >= offset:
                    ep_int = ep_int - offset
                    ep = str(ep_int) + '.' + ep_tail
            else:
                ep_int = int(ep)
                if ep_int >= offset:
                    ep = str(ep_int - offset)
        except:
            return ep

    return zero_fix(ep)


if os.path.isdir(target_path):
    logger.info(f"{'文件夹处理'}")

    # 遍历文件夹
    for root, dirs, files in os.walk(target_path, topdown=False):
        for name in files:
            # 完整文件路径
            file_path = get_absolute_path(os.path.join(root, name))

            # 删除多余文件
            if check_and_delete_redundant_file(file_path):
                logger.warning(f'多余文件, 删除 {file_path}')
                continue

            # 只处理媒体文件
            file_name, ext = get_file_name_ext(name)
            if not ext.lower() in COMPOUND_EXTS:
                continue

            parent_folder_path = os.path.dirname(file_path)
            try:
                season, ep = get_season_and_ep(file_path)
            except ValueError as e:
                logger.error(e)
                season, ep = None, None
            # 是否从父级目录获取季数
            if use_folder_as_season:
                season = get_season_cascaded(file_path)

            resolution = get_resolution_in_name(name)
            logger.info(f'识别结果: {season, ep}')
            # 重命名
            if season and ep:
                # 修正集数
                ep = ep_offset_patch(file_path, ep)
                season_path = get_season_path(file_path)
                # 系列名称
                series = get_series_from_season_path(season_path)
                # new_name = f'S{season}E{ep}' + '.' + fix_ext(ext)
                if name_format_bypass and name_format_bypass_check(
                    file_name, name_format, series, resolution_dict
                ):
                    logger.info('命名已满足 name_format 跳过')
                    continue

                new_name = clean_name(name_format.format(**locals())) + '.' + fix_ext(ext)

                if custom_replace_pair:
                    # 自定义替换关键字
                    for replace_old_part, replace_new_part in custom_replace_pair:
                        new_name = new_name.replace(replace_old_part, replace_new_part)

                logger.info(f'{new_name}')
                if move_up_to_season_folder:
                    new_path = season_path + '/' + new_name
                else:
                    new_path = parent_folder_path + '/' + new_name
                file_lists.append([format_path(file_path), format_path(new_path)])
            else:
                logger.info(f"{'未能识别 season 和 ep'}")
                unknown.append(file_path)

else:
    logger.info(f"{'单文件处理'}")
    logger.info(f'{target_path}')
    file_path = get_absolute_path(target_path)
    file_full_name = os.path.basename(file_path)
    file_name, ext = get_file_name_ext(file_full_name)
    parent_folder_path = os.path.dirname(file_path)
    if ext.lower() in COMPOUND_EXTS:
        season, ep = get_season_and_ep(file_path)
        # 是否从父级目录获取季数
        if use_folder_as_season:
            season = get_season_cascaded(file_path)

        resolution = get_resolution_in_name(file_name)
        if season and ep:
            # 修正集数
            ep = ep_offset_patch(file_path, ep)
            season_path = get_season_path(file_path)
            # 系列名称
            series = get_series_from_season_path(season_path)
            # new_name = f'S{season}E{ep}' + '.' + fix_ext(ext)
            if name_format_bypass and name_format_bypass_check(
                file_name, name_format, series, resolution_dict
            ):
                logger.info('当前命名已满足 name_format 的格式, 退出')
                exit()
            new_name = clean_name(name_format.format(**locals())) + '.' + fix_ext(ext)

            if custom_replace_pair:
                # 自定义替换关键字
                for replace_old_part, replace_new_part in custom_replace_pair:
                    new_name = new_name.replace(replace_old_part, replace_new_part)

            logger.info(f'{new_name}')
            if move_up_to_season_folder:
                new_path = format_path(season_path + '/' + new_name)
            else:
                new_path = format_path(parent_folder_path + '/' + new_name)

            file_lists.append([file_path, new_path])
        else:
            logger.info(f"{'未能识别 season 和 ep'}")
            unknown.append(file_path)

if unknown:
    logger.info(f"{'----- 未识别文件 -----'}")
    for x in unknown:
        logger.info(f'{x}')
    logger.info(f"{'--------------------'}")

if rename_delay:
    # 自动运行改名
    logger.info(f"{'重命名延迟等待中...'}")
    # 程序运行太快 会导致重命名失败 估计是文件被锁了 这里故意加个延迟(秒)
    time.sleep(rename_delay)


if file_lists:
    logger.info(f"{'----- 重命名文件列表 -----'}")
    for x in file_lists:
        logger.info(f'{x}')
    logger.info(f"{'-----------------------'}")

# 检查旧的文件数量和新的文件数量是否一致，防止文件被覆盖
new_set = set([x[1] for x in file_lists])
if len(new_set) != len(file_lists):
    logger.warning(f"{'旧文件数量和新文件数量不一致，可能会被覆盖。请检查文件命名'}")
    new_list = [x[1] for x in file_lists]
    for file in new_set:
        if new_list.count(file) > 1:
            logger.warning(f"{'重复文件', file}")
    sys.exit()

# 错误记录
error_logs = []

for old, new in file_lists:
    if not rename_overwrite:
        # 如果设置不覆盖 遇到已存在的目标文件不强制删除 只记录错误
        if os.path.exists(new):
            error_logs.append(
                f'{datetime.now().strftime("%Y-%m-%d %H:%M:%S")} 重命名 {old} 失败, 目标文件 {new} 已经存在'
            )
            continue

    # 目标文件如果存在，会导致覆盖操作的时候，优先保留满足第一组匹配规则的文件
    # 如果新文件不满足匹配，则删除新文件。
    if priority_match and os.path.exists(new):
        qrm_config = get_qrm_config(application_path)
        if qrm_config:
            logger.info('分析第一组匹配规则位满足情况')
            season_path = get_season_path(old)
            logger.info(f'season_path {season_path}')
            must_contain = ''
            for data_group in qrm_config['data_dump']['data_groups']:
                for x in data_group['data']:
                    if format_path(x['savePath']) == format_path(season_path):
                        if x['mustContain']:
                            try:
                                must_contain = x['mustContain']
                                logger.info(f"{'QRM获取到 must_contain', must_contain}")
                            except:
                                pass
            first_match = must_contain.split(' ')[0]
            logger.info(f'分离第一组匹配规则条件 first_match: {first_match}')
            if first_match:
                file_full_name = os.path.basename(old)
                if not (first_match.lower() in file_full_name.lower()):
                    logger.info('已存在文件情况下，新文件未满足第一组匹配规则，删除当前文件')
                    try:
                        os.remove(old)
                    except:
                        pass
                    continue
                else:
                    logger.info('满足优先规则，重命名当前文件')

    # 默认遇到文件存在则强制删除已存在文件
    try:
        # 检测文件能否重命名 报错直接忽略
        tmp_name = new + '.new'
        os.rename(old, tmp_name)

        # 目标文件已存在, 先删除
        if os.path.exists(new):
            os.remove(new)

        # 临时文件重命名
        os.rename(tmp_name, new)
    except:
        pass

if del_empty_folder:
    logger.info('删除空的子目录')
    delete_empty_dirs(target_path)

if error_logs:
    error_file = os.path.join(application_path, 'error.txt')
    logger.warning(f'部分文件重命名失败, 请检查{error_file}')
    if not os.path.exists(error_file):
        f = open(error_file, 'w', encoding='utf-8')
        f.write('\n'.join(error_logs))
    else:
        f = open(error_file, 'a', encoding='utf-8')
        f.write('\n' + '\n'.join(error_logs))

logger.info(f"{'运行完毕'}")
