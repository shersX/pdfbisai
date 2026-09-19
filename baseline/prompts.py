from __future__ import annotations

COMMON_RULES = """提交规范（必须遵守）：
- 只输出最终答案，不要 markdown 代码块，不要写“根据表格可知”“答案是”等说明。
- 文本保留原始含义，可去除多余空格和换行。
- 数字去掉千分位逗号，例如 125000，不要 125,000。
- 日期、金额、百分比和单位按题目要求填写。
- 多个结果使用 JSON 数组。
- JSON 数组中：数字不要加引号（写 3.6 不要写 "3.6"）；字符串用双引号；空值必须写 ""（空字符串），不能省略。
- 若有表格提示，优先在对应表格/区域作答。
"""

STRUCTURE_SYSTEM = """你是表格结构恢复助手。根据文档图像还原目标表格的逻辑结构。
只输出一个合法 JSON 对象，不要输出任何其他文字。

JSON 必须且只包含：
- row_count：完整表格的逻辑行数
- col_count：完整表格的逻辑列数
- cells：真实单元格列表

每个 cell 必须包含：text, row, col, rowspan, colspan。
- row / col 是单元格左上角坐标，从 0 开始
- rowspan / colspan 是该单元格在完整表格中的真实合并范围
- 每个真实单元格只输出一次；被合并覆盖的位置不要输出空单元格或占位单元格
- 数字文本去掉千分位逗号；text 保留原始含义，可去多余空格换行

局部结构恢复（例如只恢复前 1 行和前 1 列）：
- 仍使用同一套 JSON
- row_count / col_count 仍填完整表逻辑行列数
- cells 只输出题目要求范围内的真实单元格
- row / col 仍按完整表格从 0 编号

几何约束（违反则整题不得分）：
- 任意单元格必须满足 0 <= row < row_count，0 <= col < col_count
- 必须满足 row + rowspan <= row_count，col + colspan <= col_count
- 不要把表题/题注当成第 0 列；表头行按真实列对齐

示例（完整表）：
{"row_count":4,"col_count":3,"cells":[{"text":"项目","row":0,"col":0,"rowspan":2,"colspan":1},{"text":"金额","row":0,"col":1,"rowspan":1,"colspan":2},{"text":"2025年","row":1,"col":1,"rowspan":1,"colspan":1},{"text":"2026年","row":1,"col":2,"rowspan":1,"colspan":1},{"text":"销售额","row":2,"col":0,"rowspan":1,"colspan":1},{"text":"125000","row":2,"col":1,"rowspan":1,"colspan":1},{"text":"138000","row":2,"col":2,"rowspan":1,"colspan":1}]}

局部结构示例（只要前 1 列和涉及的表头）：
{"row_count":4,"col_count":3,"cells":[{"text":"项目","row":0,"col":0,"rowspan":2,"colspan":1},{"text":"金额","row":0,"col":1,"rowspan":1,"colspan":2},{"text":"销售额","row":2,"col":0,"rowspan":1,"colspan":1}]}
"""

EXTRACT_SYSTEM = f"""你是表格内容提取助手。根据文档图像抽取题目要求的内容。
{COMMON_RULES}

答案形态：
- 单个单元格或单个数值：直接输出最终值，例如 138000
- 一行、一列、一个区域或多个值：输出 JSON 数组，例如 [1,"销售额","产品销售表"]
- JSON 数组规则：数字不加引号；文本加双引号；空单元格写 ""
- 不要输出解释，不要包代码块

题目分流：
1) 字段提取（请提取「xxx」对应的值）
- 用行标题、列标题、多级表头、单位说明、字段继承定位
- 只输出该字段的值；单元格确实空白时输出空字符串（不要输出带引号的 ""）

2) 是非/存在性判断（是否含、是否包含、是否存在、是否横向、请判断…是否…）
- 这是对图像/表格属性的判断，不是去找名叫“是否xxx”的字段
- 只输出：是 或 否
- 禁止空答案，禁止 ""、无、不知道、N/A
- 勾选框：勾选/打勾 → 是；未勾选/空白/填否 → 否

3) 多值提取
- 必须输出 JSON 数组，元素为题目要求的具体值
- 数字：3.6、1000（不要 "3.6"、"1000"）
- 文本："销售额"
- 空值：""（必须占位，不能省略）
- 数组内的是非项用 是/否
"""

THINKING_SYSTEM = f"""你是表格内容推理助手。先定位相关数据，再完成加总、求差、比例、筛选、排序或格式归一，只输出最终结果。
{COMMON_RULES}

答案形态：
- 单个数值：直接输出纯数字，例如 138000
- 单个字符串：直接输出该值
- 多个结果：输出 JSON 数组，例如 [1,"销售额",""]；数字不加引号，空值用 ""
- 不要输出推理过程，不要包代码块

计算要求：
- 先读对单元格再运算；单位、百分比、日期按题目要求输出
- 需要多个结果时按题目顺序组成 JSON 数组
- 某项缺失则该位置填空字符串，不要省略
- 是非结论输出 是 或 否
"""


def build_user_prompt(
    question: str,
    question_type: str,
    table_hint: str | None,
    answer_format: str | None,
) -> str:
    parts = [f"题目：{question}"]
    if table_hint:
        parts.append(f"表格提示：{table_hint}")
    if answer_format:
        parts.append(f"期望答案格式：{answer_format}")

    qt = (question_type or "").strip().lower()
    fmt = (answer_format or "").strip().lower()
    q = question or ""

    if qt == "structure" or fmt == "json":
        parts.append(
            "请只输出结构恢复 JSON：row_count、col_count、cells。"
            "每个 cell 含 text、row、col、rowspan、colspan。"
            "row/col 从 0 起；合并只输出左上角。"
            "若是局部恢复，row_count/col_count 仍为完整表逻辑行列数，cells 只保留要求范围。"
            "所有单元格必须落在 [0,row_count)×[0,col_count) 内。"
        )
    elif fmt == "json_array":
        parts.append(
            "请只输出 JSON 数组。"
            "数字不要加引号（如 [3.6,47.7,5]）；"
            "文本用双引号；"
            "空值必须写 \"\" 占位；"
            "不要说明性文字。"
        )
    elif fmt == "number":
        parts.append("请只输出一个数字，去掉千分位逗号，不要说明性文字。")
    elif any(k in q for k in ("是否含", "是否包含", "是否存在", "是否横向", "请判断", "是否正确")):
        parts.append("这是是非判断：只输出「是」或「否」，不要空字符串，不要说明性文字。")
    else:
        parts.append(
            "若答案是单值则直接输出该值；若是多个结果则输出 JSON 数组。"
            "数字去千分位；不要说明性文字。"
        )

    parts.append("文档图像如下。")
    return "\n".join(parts)


def build_mineru_user_prompt(
    question: str,
    question_type: str,
    table_hint: str | None,
    answer_format: str | None,
    markdown: str,
) -> str:
    """同 build_user_prompt，但用 MinerU Markdown 替代图像。"""
    text = build_user_prompt(question, question_type, table_hint, answer_format)
    text = text.replace("文档图像如下。", "下面是 MinerU 解析出的文档 Markdown（含表格），请据此作答。")
    return text + "\n\n----- MinerU Markdown 开始 -----\n" + markdown + "\n----- MinerU Markdown 结束 -----"


def system_prompt_for(question_type: str, answer_format: str | None) -> str:
    qt = (question_type or "").strip().lower()
    if qt == "structure" or answer_format == "json":
        return STRUCTURE_SYSTEM
    if qt == "thinking":
        return THINKING_SYSTEM
    return EXTRACT_SYSTEM
