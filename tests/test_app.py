"""
Tests for Law Firm Feedback Analysis application
"""

import pytest
import os
import tempfile
from app import app, init_db


@pytest.fixture
def client():
    """Create a test client for the app"""
    # Create a temporary database
    db_fd, db_path = tempfile.mkstemp()
    app.config['DATABASE_PATH'] = db_path
    app.config['TESTING'] = True
    
    with app.test_client() as client:
        with app.app_context():
            init_db()
        yield client
    
    # Clean up
    os.close(db_fd)
    os.unlink(db_path)


def test_home_page_loads(client):
    """Test that the home page loads successfully"""
    response = client.get('/')
    assert response.status_code == 200
    assert b'Client Feedback Analysis' in response.data


def test_feedback_form_loads(client):
    """Test that the feedback form page loads"""
    response = client.get('/feedback')
    assert response.status_code == 200
    assert b'Share Your Feedback' in response.data


def test_feedback_submission(client):
    """Test submitting client feedback"""
    response = client.post('/feedback', data={
        'date': '2024-01-15',
        'rating': '5',
        'review_text': 'Excellent service and communication!'
    }, follow_redirects=True)
    
    assert response.status_code == 200
    assert b'Thank You for Your Feedback!' in response.data


def test_feedback_submission_missing_fields(client):
    """Test that feedback submission fails without required fields"""
    response = client.post('/feedback', data={
        'date': '2024-01-15'
        # Missing rating and review_text
    }, follow_redirects=True)
    
    assert b'Please provide a rating and review text' in response.data


def test_login_page_loads(client):
    """Test that the login page loads"""
    response = client.get('/login')
    assert response.status_code == 200
    assert b'Admin Login' in response.data


def test_invalid_login(client):
    """Test login with invalid credentials"""
    response = client.post('/login', data={
        'username': 'wronguser',
        'password': 'wrongpass'
    }, follow_redirects=True)
    
    assert b'Invalid username or password' in response.data


def test_valid_login(client):
    """Test login with valid default credentials"""
    response = client.post('/login', data={
        'username': 'admin',
        'password': 'changeme123'
    }, follow_redirects=True)
    
    assert response.status_code == 200


def test_dashboard_requires_auth(client):
    """Test that dashboard requires authentication"""
    response = client.get('/dashboard')
    # Should redirect to login
    assert response.status_code == 302
    assert '/login' in response.location


def test_csv_upload_requires_auth(client):
    """Test that CSV upload requires authentication"""
    response = client.get('/upload')
    # Should redirect to login
    assert response.status_code == 302
    assert '/login' in response.location


def test_invalid_csv_upload(client):
    """Test CSV upload with invalid file"""
    # Login first
    client.post('/login', data={
        'username': 'admin',
        'password': 'changeme123'
    })
    
    # Try to upload a non-CSV file
    response = client.post('/upload', data={
        'file': (tempfile.NamedTemporaryFile(suffix='.txt'), 'test.txt')
    }, follow_redirects=True)
    
    assert b'Please upload a CSV file' in response.data


def test_csv_upload_with_valid_data(client):
    """Test CSV upload with valid review data"""
    # Login first
    client.post('/login', data={
        'username': 'admin',
        'password': 'changeme123'
    })
    
    # Create a valid CSV in memory
    csv_data = b'''date,rating,review_text
2024-01-15,5,"Great legal services"
2024-01-14,4,"Very professional team"
2024-01-13,3,"Satisfactory experience"'''
    
    from io import BytesIO
    response = client.post('/upload', data={
        'file': (BytesIO(csv_data), 'reviews.csv')
    }, content_type='multipart/form-data', follow_redirects=True)
    
    assert response.status_code == 200
    # Should show success message
    assert b'imported' in response.data.lower()


def test_pdf_download_without_reviews(client):
    """Test that PDF download handles empty database gracefully"""
    # Login first
    client.post('/login', data={
        'username': 'admin',
        'password': 'changeme123'
    })
    
    response = client.get('/download-pdf', follow_redirects=True)
    assert b'No reviews available' in response.data


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
