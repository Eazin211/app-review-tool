# LaienTech Review Analysis

AI-powered App Store review analysis pipeline that transforms user reviews into actionable product requirements and test plans.

## 🌟 Features

- **Multi-source Data Collection**: Fetch reviews via App Store RSS feed, import JSON/CSV, or use sample data
- **Deterministic Data Cleaning**: Automated deduplication, normalization, and filtering
- **AI-Driven Theme Discovery**: LLM-powered dynamic analysis (not just keyword matching)
- **Automated PRD Generation**: Structured product requirements with full traceability
- **Test Case Generation**: Requirements-linked test cases with coverage tracking
- **Traceability Validation**: End-to-end verification from reviews → findings → requirements → tests
- **Export Pipeline**: Download any intermediate or final deliverable as JSON

## 🚀 Quick Start

### Prerequisites

- Python 3.9+
- pip

### Installation

```bash
# Clone the repository
git clone <repo-url>
cd LaienTech-Review-Analysis

# Install dependencies
pip install -r requirements.txt

# Configure environment (optional - for LLM-powered analysis)
cp .env.example .env
# Edit .env and add your API key:
# OPENAI_API_KEY=your_actual_api_key_here
```

### Running the App

```bash
streamlit run app.py
```

Open your browser and navigate to `http://localhost:8501`

## 🏗️ Architecture

### Pipeline Stages

1. **Data Collection** (`modules/scraper.py`)
   - Primary: iTunes RSS Customer Reviews API
   - URL Pattern: `https://itunes.apple.com/{country}/rss/customerreviews/id={app_id}/page={n}/json`
   - Fallback: Import from JSON/CSV files
   - Sample: Pre-loaded cached reviews for offline demonstration
   - **Rate Limiting**: 0.5s delay between requests, max 10 pages (~500 reviews)

2. **Data Cleaning** (`modules/cleaner.py`)
   - Empty content removal (deterministic rule)
   - Deduplication by review ID and content hash (deterministic rule)
   - Field normalization (dates, ratings, text)
   - Missing field handling with defaults

3. **AI Analysis** (`modules/analyzer.py`)
   - **Primary**: LLM-based dynamic theme discovery
     - Batches reviews for processing (up to 30 per batch)
     - Identifies themes, findings, and patterns dynamically
     - Provides confidence scores and support counts
     - Detects contradictions in feedback
   - **Fallback**: Statistical baseline analysis when no API key
     - Rating-based sentiment analysis
     - Basic positive/negative categorization

4. **PRD Generation** (`modules/prd_generator.py`)
   - Transforms findings into structured requirements
   - Assigns priorities (Must Have / Should Have / Nice to Have)
   - Plans multi-phase release roadmap
   - Maintains traceability to source reviews
   - LLM-enhanced requirement generation when available

5. **Test Case Generation** (`modules/testcase_generator.py`)
   - Generates test cases mapped to PRD requirements
   - Includes preconditions, steps, and expected results
   - Priority and type classification
   - Coverage tracking and reporting
   - LLM-enhanced test case generation when available

6. **Validation** (`modules/validator.py`)
   - Verifies full traceability chain integrity
   - Detects orphaned reviews, findings, or requirements
   - Flags unsupported claims
   - Generates traceability matrix
   - Reports issues and warnings

### Module Structure

```
LaienTech-Review-Analysis/
├── app.py                  # Streamlit main entry point
├── requirements.txt        # Python dependencies
├── .env.example            # Environment variable template
├── README.md              # This file
├── modules/
│   ├── __init__.py
│   ├── scraper.py          # Data collection (RSS + import)
│   ├── cleaner.py          # Data cleaning & deduplication
│   ├── analyzer.py         # AI dynamic analysis (core)
│   ├── prd_generator.py    # PRD document generation
│   ├── testcase_generator.py  # Test case generation
│   └── validator.py        # Traceability validation
└── sample_data/
    └── sample_reviews.json # Cached sample reviews
```

## 📊 Data Sources

### Primary: App Store RSS Feed

The application uses Apple's official iTunes RSS Customer Reviews API:

- **Endpoint**: `https://itunes.apple.com/{country}/rss/customerreviews/id={APP_ID}/sortBy=mostRecent/page={PAGE}/json`
- **Rate Limit**: ~500 reviews total (10 pages × 50 reviews)
- **Fields**: Review ID, title, content, rating, author, version, date
- **Limitation**: No pagination beyond 10 pages, limited to most recent reviews

### Alternative Sources

- **JSON Import**: File with array of review objects or `{"reviews": [...]}` format
- **CSV Import**: File with columns matching review fields
- **Sample Data**: Pre-loaded "Workout for Women" reviews for offline testing

## 🤖 AI/ML Configuration

### LLM Setup

1. Copy `.env.example` to `.env`
2. Configure your API provider:

```
# Option 1: OpenAI
OPENAI_API_KEY=sk-your-key-here
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o

# Option 2: Compatible API (e.g., Ollama, Azure, etc.)
OPENAI_API_KEY=your-key
OPENAI_BASE_URL=https://your-provider.com/v1
OPENAI_MODEL=your-model-name
```

### What the LLM Does

The LLM is used for **semantic understanding** tasks that cannot be reduced to deterministic rules:

1. **Dynamic Theme Discovery**: Identifies emergent topics/themes from review content without predefined categories
2. **Finding Generation**: Extracts specific problems, feature requests, and sentiments with evidence
3. **Requirement Generation**: Translates findings into well-structured product requirements
4. **Test Case Generation**: Creates actionable test cases from requirements
5. **Confidence Assessment**: Evaluates how well-supported each finding is

### How Hallucination is Reduced

- Review IDs are passed explicitly in prompts for traceability
- LLM responses are parsed and validated against required JSON schema
- All model-generated claims are cross-referenced with source data
- Statistical measures (support count, confidence) are computed deterministically
- Fallback to rule-based analysis when LLM is unavailable
- Error handling with graceful degradation

### Deterministic vs. Model-Driven

| Stage | Method | Rationale |
|-------|--------|-----------|
| Data Collection | Deterministic (RSS/import) | Structured data sources, no ambiguity |
| Deduplication | Deterministic (hash-based) | Exact matching required |
| Normalization | Deterministic (rules) | Format standardization |
| Theme Discovery | **LLM-driven** | Emergent patterns require semantic understanding |
| Finding Extraction | **LLM-driven** | Understanding context and nuance |
| Confidence Scoring | Hybrid (LLM + statistical) | Model judgment + statistical grounding |
| Requirement Gen | **LLM-driven** | Creative synthesis from analysis |
| Test Case Gen | **LLM-driven** | Generating actionable steps |
| Validation | Deterministic (graph checks) | Verifying structural integrity |

## 📤 Importing Custom Data

### JSON Format

```json
[
  {
    "review_id": "unique_id",
    "title": "Review title",
    "content": "Full review text",
    "rating": 5,
    "author": "Username",
    "version": "3.2.1",
    "date": "2024-01-15T10:30:00Z",
    "app_name": "App Name"
  }
]
```

### CSV Format

```csv
review_id,title,content,rating,author,version,date
123,Great app,Loved it!,5,User1,3.2.1,2024-01-15
```

## 📖 Deliverables

The pipeline generates these outputs at each stage:

1. **Raw Reviews**: Unprocessed data from the source
2. **Cleaned Reviews**: Deduplicated, normalized, filtered
3. **Analysis**: Themes, findings, confidence scores, contradictions
4. **PRD**: Requirements with priorities, release plan, traceability
5. **Test Cases**: Steps, expected results, coverage metrics
6. **Validation**: Traceability matrix, issues, warnings

All outputs are downloadable as JSON files.

## 🔒 Security

- API keys are stored in `.env` file (not committed to repository)
- No secrets in source code or configuration files
- Input validation on all data sources
- No external network calls beyond App Store RSS and LLM API
- Rate limiting on all external requests

## 🛠️ Tech Stack

- **Frontend**: Streamlit
- **Backend**: Python 3.9+
- **Data Processing**: Pandas
- **API Integration**: Requests, OpenAI SDK
- **Configuration**: python-dotenv

## 📝 Notes for Evaluators

1. **Offline Mode**: Without an API key, the app uses statistical baseline analysis. The sample data demonstrates the full pipeline.
2. **New Inputs**: The app accepts any valid App Store URL, JSON, or CSV data — no app-specific hardcoding.
3. **Transparency**: All limitations, data gaps, and contradictions are explicitly reported.
4. **Traceability**: Every requirement and test case can be traced back to specific source reviews.
5. **Export**: Complete pipeline results can be exported as a single JSON package.

## 📄 License

MIT License
