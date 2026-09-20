'''关键字与定位方式清单 —— 供 Web 端下拉框使用。

来源：keywordsDriver/keywordKey.py 的常量 + Data/testdata.xlsx 的 keyword_template sheet。
桌面端关键字（start_app / get_win / mouse_click / Close_win）单独归组并标注，
存量用例里若仍引用它们，编辑时下拉还能正确回显，不会被静默吞掉。
'''

LOCATE_TYPES = [
    ('xpath', 'xpath'),
    ('id', 'id'),
    ('name', 'name'),
    ('class_name', 'class_name（class）'),
    ('link_text', 'link_text（链接全文）'),
    ('partial_link_text', 'partial_link_text（链接部分文字）'),
    ('tag_name', 'tag_name'),
    ('css_selector', 'css_selector（css）'),
]

KEYWORD_GROUPS = [
    {
        'name': '浏览器与页面',
        'items': [
            ('open_browser', '打开浏览器，本行填 Chrome/Firefox/Ie'),
            ('maxwindow', '窗口最大化'),
            ('open_url', '打开网址，本行填 URL'),
            ('Back', '返回上一页'),
            ('Refresh', '刷新页面'),
            ('close_browser', '关闭当前窗口'),
            ('Quite_browser', '退出浏览器（关闭整个会话）'),
            ('swith_window_handle_by_title', '按标题切换窗口，本行填标题'),
            ('swith_window_handle_by_index', '按序号切换窗口，本行填数字'),
            ('swith_frame', '切换 frame，本行填 id 或序号'),
        ],
    },
    {
        'name': '元素操作',
        'items': [
            ('input', '输入文本，本行填输入值'),
            ('click', '点击元素'),
            ('clear', '清空输入框'),
            ('send_keys', '键盘输入（当前焦点）'),
            ('selectbytext', '下拉框按文本选择，本行填选择值'),
            ('selectbyindex', '下拉框按序号选择，本行填选择值'),
            ('selectbyvalue', '下拉框按 value 选择，本行填选择值'),
            ('Move_mouse_to_element', '鼠标移动到元素上'),
            ('CodeSlide', '验证码滑块拖动，本行填坐标 x,y（如 300,0）'),
            ('Exeucejs', '执行 JS，定位表达式填脚本'),
            ('screenshots', '截图，报告里可见'),
            ('sleep', '等待，本行填秒数'),
        ],
    },
    {
        'name': '断言',
        'items': [
            ('assertEqual', '期望值 == 实际值'),
            ('assertNotEqual', '期望值 != 实际值'),
            ('AssertIn', '期望值 包含于 实际值'),
            ('AssertNotIn', '期望值 不包含于 实际值'),
            ('assertTrue', '实际值为真'),
            ('assert_Is_Display', '元素是否显示，期望 True/False'),
            ('assert_Is_Enabled', '元素是否可用，期望 True/False'),
            ('assert_Is_Exist', '元素是否存在，期望 True/False'),
            ('assert_Is_NotExist', '元素是否不存在，期望 True/False'),
            ('assert_Is_Number', '是否为数字'),
            ('assert_Number_between', '数值范围，本行填 最小值-最大值'),
        ],
    },
    {
        'name': '桌面端（已不使用）',
        'items': [
            ('start_app', '启动桌面程序，本行填 exe 路径'),
            ('get_win', '获取桌面窗口'),
            ('mouse_click', '鼠标点击坐标（相对窗口），本行填 x,y'),
            ('Close_win', '关闭窗口'),
        ],
    },
]

# 全部关键字及其说明，便于模板里做提示
KEYWORD_TIPS = {
    kw: tip for group in KEYWORD_GROUPS for kw, tip in group['items']
}

# 需要填写「定位方式 + 定位表达式」的关键字（用于前端自动聚焦/提示）
KEYWORDS_NEED_LOCATOR = [
    'click', 'clear', 'input', 'Move_mouse_to_element', 'CodeSlide',
    'assertEqual', 'assertNotEqual', 'AssertIn', 'AssertNotIn', 'assertTrue',
    'assert_Is_Display', 'assert_Is_Enabled', 'assert_Is_Exist',
    'assert_Is_NotExist', 'assert_Is_Number', 'assert_Number_between',
    'selectbytext', 'selectbyindex', 'selectbyvalue',
]
