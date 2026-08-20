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
    page_title="LaienTech - Review Analysis",
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
    if 'rss_metadata' not in st.session_state:
        st.session_state.rss_metadata = {}


def log(message: str):
    timestamp = datetime.now().strftime('%H:%M:%S')
    st.session_state.logs.append(f'[{timestamp}] {message}')


def render_sidebar():
    with st.sidebar:
        st.markdown("## ⚙️ Configuration")
        st.markdown("---")

        data_source = st.radio(
            "Data Source",
            ['App Store URL', 'Sample Data', 'Import JSON', 'Import CSV'],
            help="Choose how to load review data"
        )

        if data_source == 'App Store URL':
            app_url = st.text_input(
                "App Store URL",
                value="https://apps.apple.com/us/app/workout-for-women-home-gym/id839285684",
                help="Paste the full App Store URL"
            )
            if app_url:
                app_id, country = parse_app_store_url(app_url)
                if app_id:
                    st.success(f"Detected: App ID={app_id}, Country={country}")
                    st.session_state.app_info = {
                        'app_id': app_id,
                        'country': country,
                        'url': app_url
                    }
                else:
                    st.error("Could not parse App ID from URL")

        elif data_source == 'Sample Data':
            st.info("Using pre-loaded sample reviews for 'Workout for Women'")
            st.session_state.app_info = {
                'app_id': '839285684',
                'country': 'us',
                'app_name': 'Workout for Women: Home Gym',
                'is_sample': True
            }

        elif data_source == 'Import JSON':
            uploaded_file = st.file_uploader("Upload JSON file", type=['json'])
            if uploaded_file:
                try:
                    content = uploaded_file.read().decode('utf-8')
                    data = json.loads(content)
                    if isinstance(data, list):
                        st.session_state.reviews_raw = data
                    elif isinstance(data, dict) and 'reviews' in data:
                        st.session_state.reviews_raw = data['reviews']
                    st.success(f"Loaded {len(st.session_state.reviews_raw)} reviews from JSON")
                except Exception as e:
                    st.error(f"Failed to load JSON: {str(e)}")

        elif data_source == 'Import CSV':
            uploaded_file = st.file_uploader("Upload CSV file", type=['csv'])
            if uploaded_file:
                try:
                    df = pd.read_csv(uploaded_file)
                    st.session_state.reviews_raw = df.to_dict('records')
                    st.success(f"Loaded {len(st.session_state.reviews_raw)} reviews from CSV")
                except Exception as e:
                    st.error(f"Failed to load CSV: {str(e)}")

        st.markdown("---")

        st.markdown("## 🎯 Analysis Goals")
        goals_input = st.text_area(
            "Analysis goals or focus areas",
            value="subscription conversion, workout availability, low-rating reviews, user experience",
            height=100,
            help="Comma-separated list of analysis goals"
        )
        if goals_input:
            st.session_state.goals = [g.strip() for g in goals_input.split(',') if g.strip()]

        st.markdown("---")

        api_key = os.getenv('OPENAI_API_KEY', '')
        if api_key:
            st.success("🔑 LLM API key configured")
        else:
            st.warning("⚠️ No LLM API key configured — using statistical baseline only")

        st.markdown("---")

        max_pages = st.slider("RSS Pages to Fetch", 1, 10, 5, help="Number of RSS pages to fetch (max 10, ~50 reviews per page)")

        st.markdown("---")
        st.markdown("### Quick Actions")
        if st.button("🔄 Reset Pipeline", use_container_width=True):
            for key in list(st.session_state.keys()):
                if key not in ('workflow_stage', 'logs', 'goals', 'app_info', 'rss_metadata'):
                    del st.session_state[key]
            st.session_state.workflow_stage = 0
            st.session_state.logs = []
            st.session_state.rss_metadata = {}
            st.success("Pipeline reset!")
            st.rerun()

        if st.button("▶️ Start Analysis", type="primary", use_container_width=True):
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
        status_placeholder.info(f"Stage {stage}/7: {message}")

    try:
        update_progress(1, "Determining analysis scope...")
        time.sleep(0.3)

        update_progress(2, "Collecting review data...")
        source = None
        fetch_metadata = {}

        if st.session_state.get('app_info', {}).get('is_sample'):
            reviews = load_sample_data()
            source = 'sample'
            st.session_state.rss_metadata = {}
            log(f"Loaded {len(reviews)} sample reviews")
        elif st.session_state.reviews_raw:
            reviews = st.session_state.reviews_raw
            source = 'imported'
            st.session_state.rss_metadata = {}
            log(f"Using {len(reviews)} imported reviews")
        elif st.session_state.app_info.get('app_id'):
            app_id = st.session_state.app_info['app_id']
            country = st.session_state.app_info.get('country', 'us')

            with st.spinner('Fetching reviews from App Store RSS...'):
                reviews, fetch_metadata = fetch_reviews(
                    app_id=app_id,
                    country=country,
                    max_pages=max_pages,
                    progress_callback=log
                )
            source = 'rss'
            log(f"Fetched {len(reviews)} reviews from RSS")

            if not reviews:
                st.warning("RSS fetch returned no reviews, falling back to sample data.")
                reviews = load_sample_data()
                source = 'sample_fallback'
        else:
            st.error("No data source configured. Please provide a URL, import data, or use sample data.")
            st.session_state.running = False
            return

        st.session_state.reviews_raw = reviews

        if fetch_metadata.get('rss_limit_reached'):
            st.session_state.rss_metadata = fetch_metadata
            log("RSS 500-review limit reached")
        elif fetch_metadata.get('note'):
            st.session_state.rss_metadata = fetch_metadata
            log(f"RSS note: {fetch_metadata['note']}")

        if not st.session_state.app_info.get('app_name'):
            app_names = [r.get('app_name', '') for r in reviews if r.get('app_name')]
            if app_names:
                st.session_state.app_info['app_name'] = max(set(app_names), key=app_names.count)

        update_progress(3, "Cleaning, deduplicating, and structuring review data...")
        with st.spinner('Cleaning review data...'):
            cleaned, stats = clean_reviews(
                reviews,
                remove_empty=True,
                deduplicate=True,
                normalize=True,
                progress_callback=log
            )
        st.session_state.reviews_clean = cleaned
        st.session_state.clean_stats = stats
        log(f"Cleaning complete: {stats['input_count']} → {stats['output_count']} reviews")

        update_progress(4, "AI-driven dynamic theme discovery and analysis...")
        goals = st.session_state.get('goals', ['general'])
        analyzer = ReviewAnalyzer()

        with st.spinner('Running AI analysis...'):
            analysis = analyzer.analyze_reviews(
                cleaned,
                goals=goals,
                progress_callback=log
            )
        st.session_state.analysis = analysis
        log(f"Analysis complete: {len(analysis.get('themes', []))} themes, {len(analysis.get('findings', []))} findings")

        update_progress(5, "Generating PRD document...")
        prd_generator = PRDGenerator()

        with st.spinner('Generating PRD...'):
            prd = prd_generator.generate_prd(
                analysis,
                app_info=st.session_state.app_info,
                goals=goals,
                progress_callback=log
            )
        st.session_state.prd = prd
        log(f"PRD generated: {len(prd.get('requirements', []))} requirements across {len(prd.get('versions', []))} phases")

        update_progress(6, "Generating test cases...")
        tc_generator = TestCaseGenerator()

        with st.spinner('Generating test cases...'):
            test_results = tc_generator.generate_test_cases(
                prd,
                analysis,
                progress_callback=log
            )
        st.session_state.test_results = test_results
        log(f"Generated {test_results.get('total_test_cases', 0)} test cases")

        update_progress(7, "Validating traceability chain...")
        validator = TraceabilityValidator()

        with st.spinner('Validating...'):
            validation = validator.validate_pipeline(
                reviews,
                cleaned,
                analysis,
                prd,
                test_results,
                progress_callback=log
            )
        st.session_state.validation = validation
        log(f"Validation {'passed' if validation.get('valid') else 'found issues'}: {validation.get('stats', {})}")

        progress_placeholder.success("✅ Analysis pipeline complete!")
        status_placeholder.empty()

    except Exception as e:
        progress_placeholder.error(f"Pipeline failed: {str(e)}")
        log(f"Error: {str(e)}")
    finally:
        st.session_state.running = False


def render_main_content():
    st.markdown('<div class="main-header">🔍 LaienTech Review Analysis</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-header">AI-Powered App Store Review Analysis → PRD Generation → Test Case Generation</div>', unsafe_allow_html=True)

    app_info = st.session_state.get('app_info', {})
    if app_info:
        st.markdown(f"**Target App:** {app_info.get('app_name', app_info.get('app_id', 'Unknown'))} | **Country:** {app_info.get('country', 'N/A').upper()}")

    if not st.session_state.get('reviews_raw'):
        render_empty_state()
        return

    render_pipeline_status()

    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "📊 Raw Data", "🧹 Cleaned Data", "🔍 Analysis",
        "📋 PRD", "🧪 Test Cases", "✅ Validation"
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
            <h2 style="color: #667eea; margin-bottom: 8px;">Start Your Analysis</h2>
            <p style="color: #666; font-size: 16px;">
                Configure your data source and analysis goals in the sidebar, then click <strong>"Start Analysis"</strong><br><br>
                <strong>Pipeline Stages:</strong><br>
                1️⃣ Collect App Store reviews via RSS<br>
                2️⃣ Clean, deduplicate, and normalize data<br>
                3️⃣ AI-driven dynamic theme discovery<br>
                4️⃣ Generate structured PRD (with traceability)<br>
                5️⃣ Generate test cases from requirements<br>
                6️⃣ Validate full traceability chain
            </p>
        </div>
        """, unsafe_allow_html=True)


def render_pipeline_status():
    stage = st.session_state.get('workflow_stage', 0)
    stages = [
        "Data Collection", "Data Cleaning", "AI Analysis",
        "PRD Generation", "Test Generation", "Validation"
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
        with st.expander("📋 Execution Logs", expanded=False):
            for log_entry in st.session_state.logs[-30:]:
                st.text(log_entry)


def render_raw_data_tab():
    reviews = st.session_state.get('reviews_raw', [])
    st.markdown(f"### 📥 Raw Reviews ({len(reviews)} total)")

    rss_meta = st.session_state.get('rss_metadata', {})
    if rss_meta.get('rss_limit_reached'):
        st.warning(f"⚠️ iTunes RSS API limitation: {rss_meta.get('note', 'current data source only provides the latest 500 reviews')}")
    elif rss_meta.get('note'):
        st.info(f"ℹ️ Data source note: {rss_meta['note']}")

    if reviews:
        df = pd.DataFrame(reviews)
        display_cols = [c for c in ['review_id', 'title', 'content', 'rating', 'author', 'version', 'date'] if c in df.columns]
        if display_cols:
            df_display = df[display_cols].copy()
            df_display['rating'] = df_display['rating'].apply(lambda x: f"{'⭐' * int(x)}" if pd.notna(x) else '')
            st.dataframe(df_display.head(50), use_container_width=True, hide_index=True)

        st.download_button(
            "📥 Download Raw Data (JSON)",
            data=json.dumps(reviews, indent=2, ensure_ascii=False),
            file_name="raw_reviews.json",
            mime="application/json"
        )


def render_cleaned_data_tab():
    cleaned = st.session_state.get('reviews_clean', [])
    stats = st.session_state.get('clean_stats', {})

    st.markdown("### 🧹 Cleaned & Deduplicated Reviews")

    if stats:
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.markdown(f'<div class="metric-card"><div style="color:#666;font-size:12px">Input</div><div style="font-size:24px;font-weight:700">{stats.get("input_count", 0)}</div></div>', unsafe_allow_html=True)
        with col2:
            st.markdown(f'<div class="metric-card"><div style="color:#666;font-size:12px">Cleaned</div><div style="font-size:24px;font-weight:700">{stats.get("output_count", 0)}</div></div>', unsafe_allow_html=True)
        with col3:
            st.markdown(f'<div class="metric-card"><div style="color:#666;font-size:12px">Removed Empty</div><div style="font-size:24px;font-weight:700">{stats.get("removed_empty", 0)}</div></div>', unsafe_allow_html=True)
        with col4:
            st.markdown(f'<div class="metric-card"><div style="color:#666;font-size:12px">Removed Duplicates</div><div style="font-size:24px;font-weight:700">{stats.get("removed_duplicates", 0)}</div></div>', unsafe_allow_html=True)

    if cleaned:
        df = pd.DataFrame(cleaned)
        display_cols = [c for c in ['review_id', 'title', 'content', 'rating', 'author', 'version', 'date'] if c in df.columns]
        if display_cols:
            df_display = df[display_cols].copy()
            df_display['rating'] = df_display['rating'].apply(lambda x: f"{'⭐' * int(x)}" if pd.notna(x) and int(x) > 0 else '')
            st.dataframe(df_display, use_container_width=True, hide_index=True)

        st.download_button(
            "📥 Download Cleaned Data (JSON)",
            data=json.dumps(cleaned, indent=2, ensure_ascii=False),
            file_name="cleaned_reviews.json",
            mime="application/json"
        )


def render_analysis_tab():
    analysis = st.session_state.get('analysis', {})
    if not analysis:
        st.info("No analysis results yet. Please run the analysis pipeline first.")
        return

    rss_meta = st.session_state.get('rss_metadata', {})
    if rss_meta.get('rss_limit_reached'):
        st.warning(f"⚠️ iTunes RSS API limitation: {rss_meta.get('note', 'current data source only provides the latest 500 reviews')}")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(f'<div class="metric-card"><div style="color:#666;font-size:12px">Reviews Analyzed</div><div style="font-size:24px;font-weight:700">{analysis.get("total_reviews_analyzed", 0)}</div></div>', unsafe_allow_html=True)
    with col2:
        st.markdown(f'<div class="metric-card"><div style="color:#666;font-size:12px">Themes Found</div><div style="font-size:24px;font-weight:700">{len(analysis.get("themes", []))}</div></div>', unsafe_allow_html=True)
    with col3:
        model_status = "🤖 LLM Model" if analysis.get('model_used') else "📊 Statistical Baseline"
        st.markdown(f'<div class="metric-card"><div style="color:#666;font-size:12px">Analysis Method</div><div style="font-size:18px;font-weight:700">{model_status}</div></div>', unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("### 📈 Rating Statistics")
    stats = analysis.get('statistics', {})
    if stats:
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Average Rating", f"{stats.get('average_rating', 0):.1f}/5")
        with col2:
            st.metric("Total Reviews", stats.get('total_reviews', 0))
        with col3:
            st.metric("Positive (4-5★)", stats.get('rating_breakdown', {}).get('positive', 0))
        with col4:
            st.metric("Negative (1-2★)", stats.get('rating_breakdown', {}).get('negative', 0))

        rating_dist = stats.get('rating_distribution', {})
        if rating_dist:
            st.markdown("**Rating Distribution:**")
            dist_df = pd.DataFrame([
                {'Rating': f'{k}★', 'Count': v}
                for k, v in sorted(rating_dist.items(), key=lambda x: int(x[0]), reverse=True)
            ])
            st.bar_chart(dist_df.set_index('Rating'))

    st.markdown("---")
    themes = analysis.get('themes', [])
    st.markdown(f"### 🏷️ Identified Themes ({len(themes)} total)")
    for theme in themes:
        with st.expander(f"📌 {theme.get('name', 'Unknown Theme')} ({len(theme.get('source_review_ids', []))} reviews)"):
            st.write(f"**Description:** {theme.get('description', '')}")
            st.write(f"**Source Reviews:** {', '.join(theme.get('source_review_ids', [])[:10])}")

    st.markdown("---")
    findings = analysis.get('findings', [])
    st.markdown(f"### 🔍 Key Findings ({len(findings)} total)")

    for finding in findings:
        severity = finding.get('severity', 'medium')
        severity_class = f"severity-{severity}"
        confidence = finding.get('confidence', 0)
        conf_color = "#d32f2f" if confidence < 0.3 else "#f57c00" if confidence < 0.6 else "#388e3c"

        with st.expander(f"{'🔴' if severity == 'high' else '🟡' if severity == 'medium' else '🟢'} {finding.get('label', 'Unknown')} | [Severity: {severity}] | {len(finding.get('source_review_ids', []))} reviews | Confidence: {confidence:.0%}"):
            st.markdown(f"**Type:** `{finding.get('type', '')}`")
            st.markdown(f"**Description:** {finding.get('description', '')}")
            st.progress(confidence)
            st.markdown(f"**Source Review IDs:** {', '.join(str(x) for x in finding.get('source_review_ids', [])[:15])}")

    contradictions = analysis.get('contradictions', [])
    if contradictions:
        st.markdown("---")
        st.markdown("### ⚠️ Detected Contradictions")
        for contra in contradictions:
            st.warning(f"**{contra.get('description', '')}")

    st.download_button(
        "📥 Download Analysis (JSON)",
        data=json.dumps(analysis, indent=2, ensure_ascii=False, default=str),
        file_name="analysis_results.json",
        mime="application/json"
    )


def render_prd_tab():
    prd = st.session_state.get('prd', {})
    if not prd:
        st.info("No PRD document yet. Please run the analysis pipeline first.")
        return

    st.markdown("### 📋 Product Requirements Document (PRD)")

    st.markdown(f"**Title:** {prd.get('title', '')}")
    st.markdown(f"**Generated At:** {prd.get('generated_at', '')}")
    st.markdown(f"**{prd.get('executive_summary', '')}**")

    st.markdown("---")
    versions = prd.get('versions', [])
    st.markdown(f"### 🗺️ Version Plan ({len(versions)} phases)")
    for ver in versions:
        with st.expander(f"📦 {ver.get('name', '')} ({ver.get('version', '')})"):
            st.write(f"**Description:** {ver.get('description', '')}")
            st.write(f"**Estimated Effort:** {ver.get('estimated_effort', '')}")
            st.write(f"**Requirements:** {', '.join(ver.get('requirements', []))}")

    st.markdown("---")
    requirements = prd.get('requirements', [])
    st.markdown(f"### 📝 Requirements ({len(requirements)} total)")

    for req in requirements:
        priority = req.get('priority', 'Should Have')
        priority_icon = '🔴' if priority == 'Must Have' else '🟡' if priority == 'Should Have' else '🟢'

        with st.expander(f"{priority_icon} {req.get('id', '')}: {req.get('statement', '')[:100]}"):
            col1, col2 = st.columns([1, 3])
            with col1:
                st.markdown(f"**ID:** {req.get('id', '')}")
                st.markdown(f"**Priority:** {priority}")
                st.markdown(f"**Type:** {req.get('type', '')}")
                st.markdown(f"**Source Reviews:** {len(req.get('source_review_ids', []))}")
            with col2:
                st.markdown(f"**Statement:** {req.get('statement', '')}")
                st.markdown(f"**Rationale:** {req.get('rationale', '')}")
                st.markdown(f"**Source Findings:** {', '.join(req.get('source_findings', []))}")
                st.markdown("**Acceptance Criteria:**")
                for ac in req.get('acceptance_criteria', []):
                    st.markdown(f"  - {ac}")
                if req.get('source_review_ids'):
                    st.markdown(f"**Review IDs:** {', '.join(req.get('source_review_ids', [])[:10])}")

    limitations = prd.get('assumptions_and_limitations', [])
    if limitations:
        st.markdown("---")
        st.markdown("### ⚠️ Assumptions & Limitations")
        for lim in limitations:
            st.info(lim)

    st.download_button(
        "📥 Download PRD (JSON)",
        data=json.dumps(prd, indent=2, ensure_ascii=False, default=str),
        file_name="prd.json",
        mime="application/json"
    )


def render_testcases_tab():
    test_results = st.session_state.get('test_results', {})
    if not test_results:
        st.info("No test cases yet. Please run the analysis pipeline first.")
        return

    total = test_results.get('total_test_cases', 0)
    coverage = test_results.get('coverage', {})

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(f'<div class="metric-card"><div style="color:#666;font-size:12px">Total Test Cases</div><div style="font-size:24px;font-weight:700">{total}</div></div>', unsafe_allow_html=True)
    with col2:
        st.markdown(f'<div class="metric-card"><div style="color:#666;font-size:12px">Requirements Covered</div><div style="font-size:24px;font-weight:700">{coverage.get("requirements_covered", 0)}/{coverage.get("requirements_total", 0)}</div></div>', unsafe_allow_html=True)
    with col3:
        rate = coverage.get('coverage_rate', 0) * 100
        st.markdown(f'<div class="metric-card"><div style="color:#666;font-size:12px">Coverage Rate</div><div style="font-size:24px;font-weight:700">{rate:.0f}%</div></div>', unsafe_allow_html=True)

    test_cases = test_results.get('test_cases', [])
    st.markdown("---")
    st.markdown(f"### 🧪 Test Cases ({len(test_cases)} total)")

    priority_filter = st.multiselect(
        "Filter by Priority",
        options=['high', 'medium', 'low'],
        default=['high', 'medium', 'low']
    )
    type_filter = st.multiselect(
        "Filter by Type",
        options=['functional', 'ui', 'performance', 'regression'],
        default=['functional', 'ui', 'performance', 'regression']
    )

    filtered = [tc for tc in test_cases
                if tc.get('priority', 'low') in priority_filter
                and tc.get('type', '') in type_filter]

    st.markdown(f"Showing {len(filtered)} / {len(test_cases)} test cases")

    for tc in filtered:
        priority = tc.get('priority', 'low')
        p_icon = '🔴' if priority == 'high' else '🟡' if priority == 'medium' else '🟢'

        with st.expander(f"{p_icon} {tc.get('id', '')}: {tc.get('title', '')[:80]}"):
            col1, col2 = st.columns([1, 3])
            with col1:
                st.markdown(f"**ID:** {tc.get('id', '')}")
                st.markdown(f"**Type:** {tc.get('type', '')}")
                st.markdown(f"**Priority:** {priority}")
                st.markdown(f"**Requirement:** {tc.get('requirement_id', '')}")
                st.markdown(f"**Automatable:** {'✅ Yes' if tc.get('automation_feasible') else '❌ No'}")
            with col2:
                st.markdown(f"**Title:** {tc.get('title', '')}")
                st.markdown("**Preconditions:**")
                for pc in tc.get('preconditions', []):
                    st.markdown(f"  1. {pc}")
                st.markdown("**Test Steps:**")
                for i, step in enumerate(tc.get('steps', []), 1):
                    st.markdown(f"  {i}. {step}")
                st.markdown("**Expected Results:**")
                for er in tc.get('expected_results', []):
                    st.markdown(f"  ✅ {er}")
                if tc.get('source_review_ids'):
                    st.markdown(f"**Source Reviews:** {', '.join(str(x) for x in tc.get('source_review_ids', [])[:10])}")

    st.download_button(
        "📥 Download Test Cases (JSON)",
        data=json.dumps(test_results, indent=2, ensure_ascii=False, default=str),
        file_name="test_cases.json",
        mime="application/json"
    )


def render_validation_tab():
    validation = st.session_state.get('validation', {})
    if not validation:
        st.info("No validation results yet. Please run the analysis pipeline first.")
        return

    stats = validation.get('stats', {})

    passed = validation.get('valid', False)
    if passed:
        st.success("✅ **Traceability validation passed** — all links verified!")
    else:
        st.error("❌ **Validation failed** — issues found in traceability chain")

    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.markdown(f'<div class="metric-card"><div style="color:#666;font-size:12px">Reviews</div><div style="font-size:20px;font-weight:700">{stats.get("total_reviews", 0)}</div></div>', unsafe_allow_html=True)
    with col2:
        st.markdown(f'<div class="metric-card"><div style="color:#666;font-size:12px">Findings</div><div style="font-size:20px;font-weight:700">{stats.get("total_findings", 0)}</div></div>', unsafe_allow_html=True)
    with col3:
        st.markdown(f'<div class="metric-card"><div style="color:#666;font-size:12px">Requirements</div><div style="font-size:20px;font-weight:700">{stats.get("total_requirements", 0)}</div></div>', unsafe_allow_html=True)
    with col4:
        st.markdown(f'<div class="metric-card"><div style="color:#666;font-size:12px">Test Cases</div><div style="font-size:20px;font-weight:700">{stats.get("total_test_cases", 0)}</div></div>', unsafe_allow_html=True)
    with col5:
        issues = stats.get('issues_found', 0)
        warnings = stats.get('warnings_found', 0)
        st.markdown(f'<div class="metric-card"><div style="color:#666;font-size:12px">Issues / Warnings</div><div style="font-size:16px;font-weight:700;color:{"#d32f2f" if issues else "#388e3c"}">{issues} ❌ / {warnings} ⚠️</div></div>', unsafe_allow_html=True)

    issues = validation.get('issues', [])
    warnings = validation.get('warnings', [])

    if issues:
        st.markdown("---")
        st.markdown("### ❌ Issues (Must Fix)")
        for issue in issues:
            st.error(f"**[{issue.get('stage', '')}]** {issue.get('message', '')}")

    if warnings:
        st.markdown("---")
        st.markdown("### ⚠️ Warnings (Review Recommended)")
        for warning in warnings:
            st.warning(f"**[{warning.get('stage', '')}]** {warning.get('message', '')}")

    matrix = validation.get('traceability_matrix', [])
    if matrix:
        st.markdown("---")
        st.markdown("### 🔗 Traceability Matrix (Sample)")
        df_matrix = pd.DataFrame(matrix[:30])
        if not df_matrix.empty:
            df_display = df_matrix[['review_id', 'rating', 'review_excerpt', 'findings', 'requirements', 'test_cases']].copy()
            df_display['findings'] = df_display['findings'].apply(lambda x: ', '.join(x) if isinstance(x, list) else str(x))
            df_display['requirements'] = df_display['requirements'].apply(lambda x: ', '.join(x) if isinstance(x, list) else str(x))
            df_display['test_cases'] = df_display['test_cases'].apply(lambda x: ', '.join(x) if isinstance(x, list) else str(x))
            st.dataframe(df_display, use_container_width=True, hide_index=True)

    st.download_button(
        "📥 Download Full Validation Report (JSON)",
        data=json.dumps(validation, indent=2, ensure_ascii=False, default=str),
        file_name="validation_report.json",
        mime="application/json"
    )

    st.markdown("---")
    st.markdown("### 📤 Export All Results")

    rss_meta_val = st.session_state.get('rss_metadata', {})
    if rss_meta_val.get('rss_limit_reached'):
        st.warning(f"⚠️ Data limitation: {rss_meta_val.get('note', 'current data source only provides the latest 500 reviews')}")

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
        'rss_metadata': st.session_state.get('rss_metadata', {}),
        'exported_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    st.download_button(
        "📦 Download Complete Analysis Package (JSON)",
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
