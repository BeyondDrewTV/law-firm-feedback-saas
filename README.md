# Law Firm Client Feedback Analysis

A Flask-based SaaS application for collecting and analyzing client feedback for law firms.

## Features

- **Client Feedback Submission**: Public form for clients to leave reviews
- **CSV Upload**: Bulk import historical reviews via CSV
- **Analysis Dashboard**: View statistics, themes, and insights
- **PDF Reports**: Generate professional PDF summaries
- **Admin Authentication**: Secure access to admin features

## Quick Start

### 1. Set up Python environment

```bash
# Create virtual environment
python -m venv venv

# Activate virtual environment
# On macOS/Linux:
source venv/bin/activate
# On Windows:
venv\Scripts\activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment variables

Create a `.env` file (see `.env.example` for template):

```bash
cp .env.example .env
```

Edit `.env` with your settings:
- `SECRET_KEY`: Random string for session security
- `ADMIN_USERNAME`: Admin login username
- `ADMIN_PASSWORD`: Admin login password
- `FIRM_NAME`: Your law firm name

### 4. Run the application

**Development:**
```bash
python app.py
```

**Production (with Gunicorn):**
```bash
gunicorn app:app
```

The app will be available at `http://localhost:5000`

## CSV Format

When uploading reviews via CSV, use this format:

```csv
date,rating,review_text
2024-01-15,5,"Excellent service and communication throughout my case."
2024-01-14,4,"Very professional and knowledgeable attorneys."
2024-01-13,2,"Response times could be better."
```

**Required columns:**
- `date`: Date in YYYY-MM-DD format
- `rating`: Integer from 1 to 5
- `review_text`: Review content (use quotes if contains commas)

## Running Tests

```bash
pytest tests/
```

## Deployment

## Launch runbook

For production go-live, use the launch checklist at [`docs/launch-day-runbook.md`](docs/launch-day-runbook.md).


### Render/Railway

1. Connect your Git repository
2. Set environment variables in the platform dashboard
3. The app will automatically detect `PORT` from environment
4. Deploy command: `gunicorn app:app`

### Environment Variables for Production

```
SECRET_KEY=<random-secret-key>
ADMIN_USERNAME=<your-admin-username>
ADMIN_PASSWORD=<secure-password>
FIRM_NAME=<Your Law Firm Name>
DATABASE_PATH=feedback.db
FLASK_ENV=production
```

## Project Structure

```
law-firm-feedback/
├── app.py                  # Main Flask application
├── config.py               # Configuration settings
├── pdf_generator.py        # PDF report generation
├── requirements.txt        # Python dependencies
├── templates/              # HTML templates
│   ├── base.html
│   ├── index.html
│   ├── feedback_form.html
│   ├── thank_you.html
│   ├── login.html
│   ├── upload.html
│   └── report_results.html
├── static/
│   └── css/
│       └── main.css       # Styling
├── tests/                 # Test files
└── sample_data/           # Sample CSV data
```

## Default Admin Credentials

**Username:** `admin`  
**Password:** `changeme123`

⚠️ **Important:** Change these immediately in production!

## Features Overview

### Client-Facing
- **Landing Page** (`/`): Introduction and call-to-action
- **Feedback Form** (`/feedback`): Submit new reviews
- **Thank You Page** (`/thank-you`): Confirmation after submission

### Admin Dashboard
- **Login** (`/login`): Secure admin access
- **Dashboard** (`/dashboard`): View analysis and statistics
- **CSV Upload** (`/upload`): Bulk import reviews
- **PDF Download** (`/download-pdf`): Generate report

## Support

For issues or questions, please open an issue in the repository.

## License

MIT License
