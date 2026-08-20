import os
import sys
import json
import tempfile
import time
from datetime import datetime

import streamlit as st
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from modules.scraper import parse_app_store_url, fetch_reviews, import_from_json, import_from_csv, load_sample_data
from modules.cleaner import clean_reviews
from modules.analyzer import ReviewAnalyzer
from modules.prd_generator import PRDGenerator
from modules.testcase_generator import TestCaseGenerator
from modules.validator import TraceabilityValidator

st.set_page_config(
    page_title="LaienTech - 应用评测分析",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    .main-header {
        font-size: 28px;
        font-weight: 700;
        background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 8px;
    }
    .sub-header {
        font-size: 14px;
        color: #666;
        margin-bottom: 24px;
    }
    .stage-badge {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 12px;
        font-size: 12px;
        font-weight: 600;
        margin-right: 8px;
    }
    .stage-active {
        background: #e8f4fd;
        color: #1976d2;
    }
    .stage-done {
        background: #e8f5e9;
        color: #388e3c;
    }
    .stage-pending {
        background: #f5f5f5;
        color: #999;
    }
    .metric-card {
        background: #f8f9fa;
        border-radius: 8px;
        padding: 12px 16px;
        border-left: 4px solid #667eea;
    }
    .finding-card {
        background: white;
        border: 1px solid #e0e0e0;
        border-radius: 8px;
        padding: 12px;
        margin-bottom: 8px;
    }
    .severity-high { color: #d32f2f; font-weight: 600; }
    .severity-medium { color: #f57c00; font-weight: 600; }
    .severity-low { color: #388e3c; font-weight: 600; }
</style>
""", unsafe_allow_html=True)


def init_session_state():
    if 'workflow_stage' not in st.session_state:
        st.session_state.workflow_stage = 0
    if 'logs' not in st.session_state:
        st.session_state.logs = []
    if 'reviews_raw' not in st.session_state:
        st.session_state.reviews_raw = []
    if 'reviews_clean' not in st.session_state:
        st.session_state.reviews_clean = []
    if 'clean_stats' not in st.session_state:
        st.session_state.clean_stats = {}
    if 'analysis' not in st.session_state:
        st.session_state.analysis = {}
    if 'prd' not in st.session_state:
        st.session_state.prd = {}
    if 'test_results' not in st.session_state:
        st.session_state.test_results = {}
    if 'validation' not in st.session_state:
        st.session_state.validation = {}
    if 'app_info' not in st.session_state:
        st.session_state.app_info = {}
    if 'goals' not in st.session_state:
        st.session_state.goals = []
    if 'running' not in st.session_state:
        st.session_state.running = False


def log(message: str):
    timestamp = datetime.now().strftime('%H:%M:%S')
    st.session_state.logs.append(f'[{timestamp}] {message}')


def render_sidebar():
    with st.sidebar:
        st.markdown("## ⚙️ 配置")
        st.markdown("---")

        data_source = st.radio(
            "数据来源",
            ['App Store 链接', '示例数据', '导入 JSON', '导入 CSV'],
            help="选择如何加载评论数据"
        )

        if data_source == 'App Store 链接':
            app_url = st.text_input(
                "App Store 链接",
                value="https://apps.apple.com/us/app/workout-for-women-home-gym/id839285684",
                help="粘贴完整的 App Store 链接"
            )
            if app_url:
                app_id, country = parse_app_store_url(app_url)
                if app_id:
                    st.success(f"已识别：应用ID={app_id}，地区={country}")
                    st.session_state.app_info = {
                        'app_id': app_id,
                        'country': country,
                        'url': app_url
                    }
                else:
                    st.error("无法从链接中解析出应用ID")

        elif data_source == '示例数据':
            st.info("使用预置的「Workout for Women」示例评论数据")
            st.session_state.app_info = {
                'app_id': '839285684',
                'country': 'us',
                'app_name': 'Workout for Women: Home Gym',
                'is_sample': True
            }

        elif data_source == '导入 JSON':
            uploaded_file = st.file_uploader("上传 JSON 文件", type=['json'])
            if uploaded_file:
                try:
                    content = uploaded_file.read().decode('utf-8')
                    data = json.loads(content)
                    if isinstance(data, list):
                        st.session_state.reviews_raw = data
                    elif isinstance(data, dict) and 'reviews' in data:
                        st.session_state.reviews_raw = data['reviews']
                    st.success(f"已从 JSON 加载 {len(st.session_state.reviews_raw)} 条评论")
                except Exception as e:
                    st.error(f"加载 JSON 失败：{str(e)}")

        elif data_source == '导入 CSV':
            uploaded_file = st.file_uploader("上传 CSV 文件", type=['csv'])
            if uploaded_file:
                try:
                    df = pd.read_csv(uploaded_file)
                    st.session_state.reviews_raw = df.to_dict('records')
                    st.success(f"已从 CSV 加载 {len(st.session_state.reviews_raw)} 条评论")
                except Exception as e:
                    st.error(f"加载 CSV 失败：{str(e)}")

        st.markdown("---")

        st.markdown("## 🎯 分析目标")
        goals_input = st.text_area(
            "分析目标或关注领域",
            value="订阅转化率, 锻炼可用性, 低评分评论, 用户体验",
            height=100,
            help="用逗号分隔的分析目标列表"
        )
        if goals_input:
            st.session_state.goals = [g.strip() for g in goals_input.split(',') if g.strip()]

        st.markdown("---")

        api_key = os.getenv('OPENAI_API_KEY', '')
        if api_key:
            st.success("🔑 LLM API 密钥已配置")
        else:
            st.warning("⚠️ 未配置 LLM API 密钥 — 仅使用统计基线分析")

        st.markdown("---")

        max_pages = st.slider("RSS 抓取页数", 1, 10, 5, help="从 RSS 获取的页数（最多10页，每页约50条评论）")

        st.markdown("---")
        st.markdown("### 快捷操作")
        if st.button("🔄 重置流程", use_container_width=True):
            for key in list(st.session_state.keys()):
                if key not in ('workflow_stage', 'logs', 'goals', 'app_info'):
                    del st.session_state[key]
            st.session_state.workflow_stage = 0
            st.session_state.logs = []
            st.success("流程已重置！")
            st.rerun()

        if st.button("▶️ 开始分析", type="primary", use_container_width=True):
            run_analysis_pipeline(max_pages)


def run_analysis_pipeline(max_pages: int):
    st.session_state.running = True
    st.session_state.logs = []
    st.session_state.workflow_stage = 1

    progress_placeholder = st.empty()
    status_placeholder = st.empty()

    def update_progress(stage: int, message: str):
        st.session_state.workflow_stage = stage
        log(message)
        status_placeholder.info(f"阶段 {stage}/7：{message}")

    try:
        update_progress(1, "确定分析范围...")
        time.sleep(0.3)

        update_progress(2, "收集评论数据...")
        source = None

        if st.session_state.get('app_info', {}).get('is_sample'):
            reviews = load_sample_data()
            source = 'sample'
            log(f"已加载 {len(reviews)} 条示例评论")
        elif st.session_state.reviews_raw:
            reviews = st.session_state.reviews_raw
            source = 'imported'
            log(f"使用 {len(reviews)} 条导入的评论")
        elif st.session_state.app_info.get('app_id'):
            app_id = st.session_state.app_info['app_id']
            country = st.session_state.app_info.get('country', 'us')

            with st.spinner('正在从 App Store RSS 获取评论...'):
                reviews = fetch_reviews(
                    app_id=app_id,
                    country=country,
                    max_pages=max_pages,
                    progress_callback=log
                )
            source = 'rss'
            log(f"已从 RSS 获取 {len(reviews)} 条评论")

            if not reviews:
                st.warning("RSS 获取未返回评论，回退到示例数据。")
                reviews = load_sample_data()
                source = 'sample_fallback'
        else:
            st.error("未配置数据源，请提供链接、导入数据或使用示例数据。")
            st.session_state.running = False
            return

        st.session_state.reviews_raw = reviews

        if not st.session_state.app_info.get('app_name'):
            app_names = [r.get('app_name', '') for r in reviews if r.get('app_name')]
            if app_names:
                st.session_state.app_info['app_name'] = max(set(app_names), key=app_names.count)

        update_progress(3, "清洗、去重并结构化评论数据...")
        with st.spinner('正在清洗评论数据...'):
            cleaned, stats = clean_reviews(
                reviews,
                remove_empty=True,
                deduplicate=True,
                normalize=True,
                progress_callback=log
            )
        st.session_state.reviews_clean = cleaned
        st.session_state.clean_stats = stats
        log(f"清洗完成：{stats['input_count']} → {stats['output_count']} 条评论")

        update_progress(4, "AI驱动的动态主题发现与分析...")
        goals = st.session_state.get('goals', ['general'])
        analyzer = ReviewAnalyzer()

        with st.spinner('正在运行AI分析...'):
            analysis = analyzer.analyze_reviews(
                cleaned,
                goals=goals,
                progress_callback=log
            )
        st.session_state.analysis = analysis
        log(f"分析完成：{len(analysis.get('themes', []))} 个主题，{len(analysis.get('findings', []))} 项发现")

        update_progress(5, "生成PRD文档...")
        prd_generator = PRDGenerator()

        with st.spinner('正在生成PRD...'):
            prd = prd_generator.generate_prd(
                analysis,
                app_info=st.session_state.app_info,
                goals=goals,
                progress_callback=log
            )
        st.session_state.prd = prd
        log(f"PRD已生成：{len(prd.get('requirements', []))} 项需求，分 {len(prd.get('versions', []))} 个阶段")

        update_progress(6, "生成测试用例...")
        tc_generator = TestCaseGenerator()

        with st.spinner('正在生成测试用例...'):
            test_results = tc_generator.generate_test_cases(
                prd,
                analysis,
                progress_callback=log
            )
        st.session_state.test_results = test_results
        log(f"已生成 {test_results.get('total_test_cases', 0)} 个测试用例")

        update_progress(7, "验证追溯链...")
        validator = TraceabilityValidator()

        with st.spinner('正在验证...'):
            validation = validator.validate_pipeline(
                reviews,
                cleaned,
                analysis,
                prd,
                test_results,
                progress_callback=log
            )
        st.session_state.validation = validation
        log(f"验证{'通过' if validation.get('valid') else '发现问题'}：{validation.get('stats', {})}")

        progress_placeholder.success("✅ 分析流程已完成！")
        status_placeholder.empty()

    except Exception as e:
        progress_placeholder.error(f"流程失败：{str(e)}")
        log(f"错误：{str(e)}")
    finally:
        st.session_state.running = False


def render_main_content():
    st.markdown('<div class="main-header">🔍 LaienTech 应用评测分析</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-header">AI驱动的App Store评论分析 → PRD生成 → 测试用例生成 全流程</div>', unsafe_allow_html=True)

    app_info = st.session_state.get('app_info', {})
    if app_info:
        st.markdown(f"**目标应用：** {app_info.get('app_name', app_info.get('app_id', '未知'))} | **地区：** {app_info.get('country', 'N/A').upper()}")

    if not st.session_state.get('reviews_raw'):
        render_empty_state()
        return

    render_pipeline_status()

    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "📊 原始数据", "🧹 清洗数据", "🔍 分析结果",
        "📋 PRD文档", "🧪 测试用例", "✅ 验证报告"
    ])

    with tab1:
        render_raw_data_tab()

    with tab2:
        render_cleaned_data_tab()

    with tab3:
        render_analysis_tab()

    with tab4:
        render_prd_tab()

    with tab5:
        render_testcases_tab()

    with tab6:
        render_validation_tab()


def render_empty_state():
    st.markdown("---")
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("""
        <div style="text-align: center; padding: 40px 20px;">
            <div style="font-size: 64px; margin-bottom: 16px;">🚀</div>
            <h2 style="color: #667eea; margin-bottom: 8px;">开始你的分析</h2>
            <p style="color: #666; font-size: 16px;">
                在左侧边栏配置数据源和分析目标，然后点击 <strong>"开始分析"</strong><br><br>
                <strong>流程阶段：</strong><br>
                1️⃣ 通过RSS订阅收集App Store评论<br>
                2️⃣ 清洗、去重并标准化数据<br>
                3️⃣ AI驱动的动态主题发现<br>
                4️⃣ 生成结构化PRD（含追溯链）<br>
                5️⃣ 根据需求生成测试用例<br>
                6️⃣ 验证完整追溯链
            </p>
        </div>
        """, unsafe_allow_html=True)


def render_pipeline_status():
    stage = st.session_state.get('workflow_stage', 0)
    stages = [
        "数据收集", "数据清洗", "AI分析",
        "生成PRD", "生成测试", "验证追溯"
    ]

    st.markdown("---")
    cols = st.columns(len(stages))
    for i, (col, stage_name) in enumerate(zip(cols, stages)):
        stage_num = i + 2
        with col:
            if stage == 0:
                badge_class = "stage-pending"
                icon = "⏳"
            elif stage > stage_num or (stage == 7 and i == len(stages) - 1):
                badge_class = "stage-done"
                icon = "✅"
            elif stage == stage_num or (stage == 7 and i == len(stages) - 1):
                badge_class = "stage-active"
                icon = "🔄"
            else:
                badge_class = "stage-pending"
                icon = "⏳"

            st.markdown(f'<div style="text-align:center"><div style="font-size:20px">{icon}</div><div style="font-size:11px;color:#666">{stage_name}</div></div>', unsafe_allow_html=True)

    if st.session_state.get('logs'):
        with st.expander("📋 执行日志", expanded=False):
            for log_entry in st.session_state.logs[-30:]:
                st.text(log_entry)


def render_raw_data_tab():
    reviews = st.session_state.get('reviews_raw', [])
    st.markdown(f"### 📥 原始评论（共 {len(reviews)} 条）")

    if reviews:
        df = pd.DataFrame(reviews)
        display_cols = [c for c in ['review_id', 'title', 'content', 'rating', 'author', 'version', 'date'] if c in df.columns]
        if display_cols:
            df_display = df[display_cols].copy()
            df_display['rating'] = df_display['rating'].apply(lambda x: f"{'⭐' * int(x)}" if pd.notna(x) else '')
            st.dataframe(df_display.head(50), use_container_width=True, hide_index=True)

        st.download_button(
            "📥 下载原始数据 (JSON)",
            data=json.dumps(reviews, indent=2, ensure_ascii=False),
            file_name="raw_reviews.json",
            mime="application/json"
        )


def render_cleaned_data_tab():
    cleaned = st.session_state.get('reviews_clean', [])
    stats = st.session_state.get('clean_stats', {})

    st.markdown("### 🧹 清洗去重后的评论")

    if stats:
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.markdown(f'<div class="metric-card"><div style="color:#666;font-size:12px">输入</div><div style="font-size:24px;font-weight:700">{stats.get("input_count", 0)}</div></div>', unsafe_allow_html=True)
        with col2:
            st.markdown(f'<div class="metric-card"><div style="color:#666;font-size:12px">清洗后</div><div style="font-size:24px;font-weight:700">{stats.get("output_count", 0)}</div></div>', unsafe_allow_html=True)
        with col3:
            st.markdown(f'<div class="metric-card"><div style="color:#666;font-size:12px">移除空评论</div><div style="font-size:24px;font-weight:700">{stats.get("removed_empty", 0)}</div></div>', unsafe_allow_html=True)
        with col4:
            st.markdown(f'<div class="metric-card"><div style="color:#666;font-size:12px">移除重复</div><div style="font-size:24px;font-weight:700">{stats.get("removed_duplicates", 0)}</div></div>', unsafe_allow_html=True)

    if cleaned:
        df = pd.DataFrame(cleaned)
        display_cols = [c for c in ['review_id', 'title', 'content', 'rating', 'author', 'version', 'date'] if c in df.columns]
        if display_cols:
            df_display = df[display_cols].copy()
            df_display['rating'] = df_display['rating'].apply(lambda x: f"{'⭐' * int(x)}" if pd.notna(x) and int(x) > 0 else '')
            st.dataframe(df_display, use_container_width=True, hide_index=True)

        st.download_button(
            "📥 下载清洗后数据 (JSON)",
            data=json.dumps(cleaned, indent=2, ensure_ascii=False),
            file_name="cleaned_reviews.json",
            mime="application/json"
        )


def render_analysis_tab():
    analysis = st.session_state.get('analysis', {})
    if not analysis:
        st.info("暂无分析结果，请先运行分析流程。")
        return

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(f'<div class="metric-card"><div style="color:#666;font-size:12px">已分析评论</div><div style="font-size:24px;font-weight:700">{analysis.get("total_reviews_analyzed", 0)}</div></div>', unsafe_allow_html=True)
    with col2:
        st.markdown(f'<div class="metric-card"><div style="color:#666;font-size:12px">发现主题</div><div style="font-size:24px;font-weight:700">{len(analysis.get("themes", []))}</div></div>', unsafe_allow_html=True)
    with col3:
        model_status = "🤖 LLM模型" if analysis.get('model_used') else "📊 统计基线"
        st.markdown(f'<div class="metric-card"><div style="color:#666;font-size:12px">分析方法</div><div style="font-size:18px;font-weight:700">{model_status}</div></div>', unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("### 📈 评分统计")
    stats = analysis.get('statistics', {})
    if stats:
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("平均评分", f"{stats.get('average_rating', 0):.1f}/5")
        with col2:
            st.metric("评论总数", stats.get('total_reviews', 0))
        with col3:
            st.metric("好评 (4-5★)", stats.get('rating_breakdown', {}).get('positive', 0))
        with col4:
            st.metric("差评 (1-2★)", stats.get('rating_breakdown', {}).get('negative', 0))

        rating_dist = stats.get('rating_distribution', {})
        if rating_dist:
            st.markdown("**评分分布：**")
            dist_df = pd.DataFrame([
                {'评分': f'{k}★', '数量': v}
                for k, v in sorted(rating_dist.items(), key=lambda x: int(x[0]), reverse=True)
            ])
            st.bar_chart(dist_df.set_index('评分'))

    st.markdown("---")
    themes = analysis.get('themes', [])
    st.markdown(f"### 🏷️ 识别出的主题（共 {len(themes)} 个）")
    for theme in themes:
        with st.expander(f"📌 {theme.get('name', '未知主题')}（{len(theme.get('source_review_ids', []))} 条评论）"):
            st.write(f"**描述：** {theme.get('description', '')}")
            st.write(f"**来源评论：** {', '.join(theme.get('source_review_ids', [])[:10])}")

    st.markdown("---")
    findings = analysis.get('findings', [])
    st.markdown(f"### 🔍 关键发现（共 {len(findings)} 项）")

    severity_map = {'high': '高', 'medium': '中', 'low': '低'}
    type_map = {'problem': '问题', 'feature_request': '功能请求', 'positive_feedback': '正面反馈', 'question': '疑问'}

    for finding in findings:
        severity = finding.get('severity', 'medium')
        severity_class = f"severity-{severity}"
        confidence = finding.get('confidence', 0)
        conf_color = "#d32f2f" if confidence < 0.3 else "#f57c00" if confidence < 0.6 else "#388e3c"
        sev_text = severity_map.get(severity, severity)
        type_text = type_map.get(finding.get('type', ''), finding.get('type', ''))

        with st.expander(f"{'🔴' if severity == 'high' else '🟡' if severity == 'medium' else '🟢'} {finding.get('label', '未知')} | [严重度: {sev_text}] | {len(finding.get('source_review_ids', []))} 条评论 | 置信度: {confidence:.0%}"):
            st.markdown(f"**类型：** `{type_text}`")
            st.markdown(f"**描述：** {finding.get('description', '')}")
            st.progress(confidence)
            st.markdown(f"**来源评论ID：** {', '.join(str(x) for x in finding.get('source_review_ids', [])[:15])}")

    contradictions = analysis.get('contradictions', [])
    if contradictions:
        st.markdown("---")
        st.markdown("### ⚠️ 检测到的矛盾")
        for contra in contradictions:
            st.warning(f"**{contra.get('description', '')}")

    st.download_button(
        "📥 下载分析结果 (JSON)",
        data=json.dumps(analysis, indent=2, ensure_ascii=False, default=str),
        file_name="analysis_results.json",
        mime="application/json"
    )


def render_prd_tab():
    prd = st.session_state.get('prd', {})
    if not prd:
        st.info("暂无PRD文档，请先运行分析流程。")
        return

    st.markdown("### 📋 产品需求文档 (PRD)")

    st.markdown(f"**标题：** {prd.get('title', '')}")
    st.markdown(f"**生成时间：** {prd.get('generated_at', '')}")
    st.markdown(f"**{prd.get('executive_summary', '')}**")

    st.markdown("---")
    versions = prd.get('versions', [])
    st.markdown(f"### 🗺️ 版本规划（共 {len(versions)} 个阶段）")
    effort_map = {'High': '高', 'Medium': '中', 'Low': '低'}
    for ver in versions:
        with st.expander(f"📦 {ver.get('name', '')} ({ver.get('version', '')})"):
            st.write(f"**描述：** {ver.get('description', '')}")
            st.write(f"**预估工作量：** {effort_map.get(ver.get('estimated_effort', ''), ver.get('estimated_effort', ''))}")
            st.write(f"**包含需求：** {', '.join(ver.get('requirements', []))}")

    st.markdown("---")
    requirements = prd.get('requirements', [])
    st.markdown(f"### 📝 需求列表（共 {len(requirements)} 项）")

    priority_map = {'Must Have': '必须实现', 'Should Have': '应该实现', 'Nice to Have': '可选实现'}
    req_type_map = {'bug_fix': 'Bug修复', 'feature': '新功能', 'improvement': '改进', 'ui_ux': 'UI/UX'}

    for req in requirements:
        priority = req.get('priority', 'Should Have')
        priority_icon = '🔴' if priority == 'Must Have' else '🟡' if priority == 'Should Have' else '🟢'
        priority_text = priority_map.get(priority, priority)
        req_type_text = req_type_map.get(req.get('type', ''), req.get('type', ''))

        with st.expander(f"{priority_icon} {req.get('id', '')}：{req.get('statement', '')[:100]}"):
            col1, col2 = st.columns([1, 3])
            with col1:
                st.markdown(f"**编号：** {req.get('id', '')}")
                st.markdown(f"**优先级：** {priority_text}")
                st.markdown(f"**类型：** {req_type_text}")
                st.markdown(f"**来源评论数：** {len(req.get('source_review_ids', []))}")
            with col2:
                st.markdown(f"**需求描述：** {req.get('statement', '')}")
                st.markdown(f"**理由：** {req.get('rationale', '')}")
                st.markdown(f"**来源发现：** {', '.join(req.get('source_findings', []))}")
                st.markdown("**验收标准：**")
                for ac in req.get('acceptance_criteria', []):
                    st.markdown(f"  - {ac}")
                if req.get('source_review_ids'):
                    st.markdown(f"**评论ID：** {', '.join(req.get('source_review_ids', [])[:10])}")

    limitations = prd.get('assumptions_and_limitations', [])
    if limitations:
        st.markdown("---")
        st.markdown("### ⚠️ 假设与限制")
        for lim in limitations:
            st.info(lim)

    st.download_button(
        "📥 下载PRD文档 (JSON)",
        data=json.dumps(prd, indent=2, ensure_ascii=False, default=str),
        file_name="prd.json",
        mime="application/json"
    )


def render_testcases_tab():
    test_results = st.session_state.get('test_results', {})
    if not test_results:
        st.info("暂无测试用例，请先运行分析流程。")
        return

    total = test_results.get('total_test_cases', 0)
    coverage = test_results.get('coverage', {})

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(f'<div class="metric-card"><div style="color:#666;font-size:12px">测试用例总数</div><div style="font-size:24px;font-weight:700">{total}</div></div>', unsafe_allow_html=True)
    with col2:
        st.markdown(f'<div class="metric-card"><div style="color:#666;font-size:12px">已覆盖需求</div><div style="font-size:24px;font-weight:700">{coverage.get("requirements_covered", 0)}/{coverage.get("requirements_total", 0)}</div></div>', unsafe_allow_html=True)
    with col3:
        rate = coverage.get('coverage_rate', 0) * 100
        st.markdown(f'<div class="metric-card"><div style="color:#666;font-size:12px">覆盖率</div><div style="font-size:24px;font-weight:700">{rate:.0f}%</div></div>', unsafe_allow_html=True)

    test_cases = test_results.get('test_cases', [])
    st.markdown("---")
    st.markdown(f"### 🧪 测试用例（共 {len(test_cases)} 个）")

    priority_filter = st.multiselect(
        "按优先级筛选",
        options=['high', 'medium', 'low'],
        default=['high', 'medium', 'low'],
        format_func=lambda x: {'high': '高', 'medium': '中', 'low': '低'}.get(x, x)
    )
    type_filter = st.multiselect(
        "按类型筛选",
        options=['functional', 'ui', 'performance', 'regression'],
        default=['functional', 'ui', 'performance', 'regression'],
        format_func=lambda x: {'functional': '功能测试', 'ui': '界面测试', 'performance': '性能测试', 'regression': '回归测试'}.get(x, x)
    )

    filtered = [tc for tc in test_cases
                if tc.get('priority', 'low') in priority_filter
                and tc.get('type', '') in type_filter]

    st.markdown(f"显示 {len(filtered)} / {len(test_cases)} 个测试用例")

    priority_map_cn = {'high': '高', 'medium': '中', 'low': '低'}
    type_map_cn = {'functional': '功能测试', 'ui': '界面测试', 'performance': '性能测试', 'regression': '回归测试'}

    for tc in filtered:
        priority = tc.get('priority', 'low')
        p_icon = '🔴' if priority == 'high' else '🟡' if priority == 'medium' else '🟢'
        priority_text = priority_map_cn.get(priority, priority)
        type_text = type_map_cn.get(tc.get('type', ''), tc.get('type', ''))

        with st.expander(f"{p_icon} {tc.get('id', '')}：{tc.get('title', '')[:80]}"):
            col1, col2 = st.columns([1, 3])
            with col1:
                st.markdown(f"**编号：** {tc.get('id', '')}")
                st.markdown(f"**类型：** {type_text}")
                st.markdown(f"**优先级：** {priority_text}")
                st.markdown(f"**关联需求：** {tc.get('requirement_id', '')}")
                st.markdown(f"**可自动化：** {'✅ 是' if tc.get('automation_feasible') else '❌ 否'}")
            with col2:
                st.markdown(f"**标题：** {tc.get('title', '')}")
                st.markdown("**前置条件：**")
                for pc in tc.get('preconditions', []):
                    st.markdown(f"  1. {pc}")
                st.markdown("**测试步骤：**")
                for i, step in enumerate(tc.get('steps', []), 1):
                    st.markdown(f"  {i}. {step}")
                st.markdown("**预期结果：**")
                for er in tc.get('expected_results', []):
                    st.markdown(f"  ✅ {er}")
                if tc.get('source_review_ids'):
                    st.markdown(f"**来源评论：** {', '.join(str(x) for x in tc.get('source_review_ids', [])[:10])}")

    st.download_button(
        "📥 下载测试用例 (JSON)",
        data=json.dumps(test_results, indent=2, ensure_ascii=False, default=str),
        file_name="test_cases.json",
        mime="application/json"
    )


def render_validation_tab():
    validation = st.session_state.get('validation', {})
    if not validation:
        st.info("暂无验证结果，请先运行分析流程。")
        return

    stats = validation.get('stats', {})

    passed = validation.get('valid', False)
    if passed:
        st.success("✅ **追溯链验证通过** — 所有链接已验证！")
    else:
        st.error("❌ **验证未通过** — 追溯链中存在问题")

    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.markdown(f'<div class="metric-card"><div style="color:#666;font-size:12px">评论数</div><div style="font-size:20px;font-weight:700">{stats.get("total_reviews", 0)}</div></div>', unsafe_allow_html=True)
    with col2:
        st.markdown(f'<div class="metric-card"><div style="color:#666;font-size:12px">发现数</div><div style="font-size:20px;font-weight:700">{stats.get("total_findings", 0)}</div></div>', unsafe_allow_html=True)
    with col3:
        st.markdown(f'<div class="metric-card"><div style="color:#666;font-size:12px">需求数</div><div style="font-size:20px;font-weight:700">{stats.get("total_requirements", 0)}</div></div>', unsafe_allow_html=True)
    with col4:
        st.markdown(f'<div class="metric-card"><div style="color:#666;font-size:12px">测试用例数</div><div style="font-size:20px;font-weight:700">{stats.get("total_test_cases", 0)}</div></div>', unsafe_allow_html=True)
    with col5:
        issues = stats.get('issues_found', 0)
        warnings = stats.get('warnings_found', 0)
        st.markdown(f'<div class="metric-card"><div style="color:#666;font-size:12px">问题 / 警告</div><div style="font-size:16px;font-weight:700;color:{"#d32f2f" if issues else "#388e3c"}">{issues} ❌ / {warnings} ⚠️</div></div>', unsafe_allow_html=True)

    issues = validation.get('issues', [])
    warnings = validation.get('warnings', [])

    if issues:
        st.markdown("---")
        st.markdown("### ❌ 问题（必须修复）")
        for issue in issues:
            st.error(f"**[{issue.get('stage', '')}]** {issue.get('message', '')}")

    if warnings:
        st.markdown("---")
        st.markdown("### ⚠️ 警告（建议检查）")
        for warning in warnings:
            st.warning(f"**[{warning.get('stage', '')}]** {warning.get('message', '')}")

    matrix = validation.get('traceability_matrix', [])
    if matrix:
        st.markdown("---")
        st.markdown("### 🔗 追溯矩阵（示例）")
        df_matrix = pd.DataFrame(matrix[:30])
        if not df_matrix.empty:
            df_display = df_matrix[['review_id', 'rating', 'review_excerpt', 'findings', 'requirements', 'test_cases']].copy()
            df_display['findings'] = df_display['findings'].apply(lambda x: ', '.join(x) if isinstance(x, list) else str(x))
            df_display['requirements'] = df_display['requirements'].apply(lambda x: ', '.join(x) if isinstance(x, list) else str(x))
            df_display['test_cases'] = df_display['test_cases'].apply(lambda x: ', '.join(x) if isinstance(x, list) else str(x))
            st.dataframe(df_display, use_container_width=True, hide_index=True)

    st.download_button(
        "📥 下载完整验证报告 (JSON)",
        data=json.dumps(validation, indent=2, ensure_ascii=False, default=str),
        file_name="validation_report.json",
        mime="application/json"
    )

    st.markdown("---")
    st.markdown("### 📤 导出所有结果")
    all_data = {
        'app_info': st.session_state.get('app_info', {}),
        'goals': st.session_state.get('goals', []),
        'raw_reviews': st.session_state.get('reviews_raw', []),
        'cleaned_reviews': st.session_state.get('reviews_clean', []),
        'clean_stats': st.session_state.get('clean_stats', {}),
        'analysis': st.session_state.get('analysis', {}),
        'prd': st.session_state.get('prd', {}),
        'test_results': st.session_state.get('test_results', {}),
        'validation': st.session_state.get('validation', {}),
        'exported_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    st.download_button(
        "📦 下载完整分析包 (JSON)",
        data=json.dumps(all_data, indent=2, ensure_ascii=False, default=str),
        file_name="complete_analysis_package.json",
        mime="application/json"
    )


def main():
    init_session_state()
    render_sidebar()
    render_main_content()


if __name__ == '__main__':
    main()
