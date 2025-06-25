from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import PyPDF2
import pdfplumber
import re
import os
from werkzeug.utils import secure_filename
import tempfile

app = Flask(__name__)
CORS(app)

# Configuration
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['UPLOAD_FOLDER'] = tempfile.gettempdir()

ALLOWED_EXTENSIONS = {'pdf'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def extract_text_from_pdf(file_path):
    """Extract text from PDF using multiple methods for better accuracy"""
    text = ""
    
    try:
        # Try pdfplumber first (better for text extraction)
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
    except Exception as e:
        print(f"pdfplumber failed: {e}")
        
        # Fallback to PyPDF2
        try:
            with open(file_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                for page in pdf_reader.pages:
                    text += page.extract_text() + "\n"
        except Exception as e:
            print(f"PyPDF2 also failed: {e}")
            return None
    
    return text.strip()

def parse_research_paper(text):
    """Parse the extracted text into sections"""
    if not text:
        return {"sections": {}, "raw_text": ""}
    
    # Common section headers in research papers
    section_patterns = {
        'Abstract': r'(?i)\b(?:abstract|summary)\b',
        'Introduction': r'(?i)\b(?:introduction|intro)\b',
        'Literature Review': r'(?i)\b(?:literature\s+review|related\s+work|background)\b',
        'Methodology': r'(?i)\b(?:methodology|methods?|approach|experimental\s+setup)\b',
        'Results': r'(?i)\b(?:results?|findings?|experimental\s+results?)\b',
        'Discussion': r'(?i)\b(?:discussion|analysis|interpretation)\b',
        'Conclusion': r'(?i)\b(?:conclusion|conclusions?|summary|final\s+remarks?)\b',
        'References': r'(?i)\b(?:references?|bibliography|citations?|works?\s+cited)\b',
        'Acknowledgments': r'(?i)\b(?:acknowledgments?|acknowledgements?|thanks)\b',
        'Appendix': r'(?i)\b(?:appendix|appendices|supplementary)\b'
    }
    
    sections = {}
    
    # Split text into lines for processing
    lines = text.split('\n')
    current_section = None
    current_content = []
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # Check if line matches any section header
        section_found = False
        for section_name, pattern in section_patterns.items():
            if re.match(pattern, line) and len(line) < 50:  # Header shouldn't be too long
                # Save previous section
                if current_section and current_content:
                    sections[current_section] = '\n'.join(current_content).strip()
                
                # Start new section
                current_section = section_name
                current_content = []
                section_found = True
                break
        
        if not section_found and current_section:
            current_content.append(line)
    
    # Save last section
    if current_section and current_content:
        sections[current_section] = '\n'.join(current_content).strip()
    
    # If no sections found, try alternative approach
    if not sections:
        sections = extract_sections_alternative(text)
    
    return {
        "sections": sections,
        "raw_text": text
    }

def extract_sections_alternative(text):
    """Alternative method to extract sections using more flexible patterns"""
    sections = {}
    
    # Try to find abstract
    abstract_match = re.search(r'(?i)abstract[\s\n]*(.*?)(?=\n\s*(?:introduction|keywords|1\.|i\.)|$)', text, re.DOTALL)
    if abstract_match:
        sections['Abstract'] = abstract_match.group(1).strip()
    
    # Try to find introduction
    intro_match = re.search(r'(?i)(?:introduction|1\.\s*introduction)[\s\n]*(.*?)(?=\n\s*(?:methodology|methods|2\.|ii\.)|$)', text, re.DOTALL)
    if intro_match:
        sections['Introduction'] = intro_match.group(1).strip()
    
    # Try to find conclusion
    conclusion_match = re.search(r'(?i)(?:conclusion|conclusions?)[\s\n]*(.*?)(?=\n\s*(?:references|bibliography|acknowledgments)|$)', text, re.DOTALL)
    if conclusion_match:
        sections['Conclusion'] = conclusion_match.group(1).strip()
    
    return sections

def extract_title_from_text(text):
    """Extract title from the beginning of the text"""
    if not text:
        return "Untitled Paper"
    
    lines = text.split('\n')
    for line in lines[:10]:  # Check first 10 lines
        line = line.strip()
        if line and len(line) > 10 and len(line) < 200:
            # Skip common headers
            if not re.match(r'(?i)^(?:abstract|introduction|keywords|author|university)', line):
                return line
    
    return "Research Paper"

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/extract', methods=['POST'])
def extract_pdf():
    try:
        # Check if file is present in request
        if 'pdf' not in request.files:
            return jsonify({
                'success': False,
                'error': 'No PDF file provided'
            }), 400
        
        file = request.files['pdf']
        
        # Check if file is selected
        if file.filename == '':
            return jsonify({
                'success': False,
                'error': 'No file selected'
            }), 400
        
        # Check file type
        if not allowed_file(file.filename):
            return jsonify({
                'success': False,
                'error': 'Only PDF files are allowed'
            }), 400
        
        # Save file temporarily
        filename = secure_filename(file.filename)
        temp_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(temp_path)
        
        try:
            # Extract text from PDF
            extracted_text = extract_text_from_pdf(temp_path)
            
            if not extracted_text:
                return jsonify({
                    'success': False,
                    'error': 'Could not extract text from PDF. The file might be corrupted or contain only images.'
                }), 400
            
            # Parse into sections
            parsed_data = parse_research_paper(extracted_text)
            
            # Extract title
            title = extract_title_from_text(extracted_text)
            
            return jsonify({
                'success': True,
                'data': {
                    'title': title,
                    'sections': parsed_data['sections'],
                    'raw_text': parsed_data['raw_text']
                }
            })
            
        finally:
            # Clean up temporary file
            if os.path.exists(temp_path):
                os.remove(temp_path)
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'An error occurred: {str(e)}'
        }), 500

@app.errorhandler(413)
def too_large(e):
    return jsonify({
        'success': False,
        'error': 'File too large. Maximum size allowed is 16MB.'
    }), 413

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)