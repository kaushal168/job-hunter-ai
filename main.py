import os
import re
import time
import smtplib
import requests
import subprocess
from google import genai
from email.message import EmailMessage
from dotenv import load_dotenv

load_dotenv()

RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")

CV_BASE_NAME = "KaushalBaid_Software_Engineer"
CL_BASE_NAME = "KaushalBaid_Cover_Letter"

def build_org_filter(filepath="excluded_companies.txt"):
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            companies = [line.strip() for line in f if line.strip() and not line.startswith("#")]
        
        if not companies:
            return ""
            
        formatted_companies = [f"'{comp}'" for comp in companies]
        filter_string = f"! ({' | '.join(formatted_companies)})"
        return filter_string
        
    except FileNotFoundError:
        print(f"   ↳ Notice: '{filepath}' not found. Falling back to hardcoded company exclusions.")
        return ""

def fetch_jobs():
    """Fetches targeted jobs using the RapidAPI LinkedIn endpoint with AI filters."""
    print("Fetching jobs from RapidAPI...")
    url = "https://linkedin-job-search-api.p.rapidapi.com/active-jb-24h"
    
    querystring = {
        "limit": "15",
        "offset": "0",
        "advanced_title_filter": "('Software Engineer' | Backend | Java | SDE) & ! (Test | QA | SDET | Automation | Support | Intern | Trainee | Lead | Freelance | Contract | Mobile | Tutor)",
        "advanced_organization_filter": "! ('Wells Fargo' | Infosys | TCS | 'Tata Consultancy Services' | Wipro | Cognizant | 'Tech Mahindra' | Accenture | Capgemini | HCL | IBM | LTIMindtree | Mindtree | Deloitte | PwC | EY | KPMG)", 
        "location_filter": 'India -"Chennai"',
        "description_filter": "Java OR Python OR 'C++'",
        "description_type": "text",
        "agency": "false",
        "employees_gte": "500",
        "include_ai": "true",
        "ai_experience_level_filter": "0-2,2-5"
    }
    
    org_filter = build_org_filter()
    if org_filter:
        querystring["advanced_organization_filter"] = org_filter
    
    headers = {
        "x-rapidapi-key": RAPIDAPI_KEY,
        "x-rapidapi-host": "linkedin-job-search-api.p.rapidapi.com"
    }

    try:
        response = requests.get(url, headers=headers, params=querystring)
        response.raise_for_status()
        return response.json() 
    except Exception as e:
        print(f"Error fetching jobs: {e}")
        return []

def clean_latex_output(raw_text):
    """Removes markdown artifacts regardless of how the LLM formats them."""
    cleaned = re.sub(r'```(?:latex|tex)?\n?', '', raw_text, flags=re.IGNORECASE)
    cleaned = cleaned.replace('```', '')
    return cleaned.strip()

def sanitize_latex(tex_string):
    """Adds a programmatic safety net for unescaped characters."""
    tex_string = re.sub(r'(?<!\\)&', r'\&', tex_string)
    return tex_string

def evaluate_and_tailor(job, base_cv, base_cl):
    client = genai.Client(api_key=GEMINI_API_KEY)

    title = job.get("title", "Software Engineer")
    company = job.get("organization", "the company")
    reqs = job.get("ai_requirements_summary", "")
    resp = job.get("ai_core_responsibilities", "")

    prompt = f"""
    ROLE: You are an elite Technical Recruiter and Expert Resume Writer specializing in FAANG and High-Frequency Trading (HFT) placements. 

    CANDIDATE CONTEXT:
    - Name: Kaushal
    - Target Role: Backend Software Engineer / Full Stack Engineer.
    - Current Experience: 1.5 YOE Java Developer.
    
    VOICE & STYLE CONSTRAINTS:
    - Maintain the existing XYZ bullet point format (Action Verb + Quantifiable Metric + Technology Used).
    - Keep ALL bullet points in the past tense (e.g., "Architected", "Built"), even for the current role.
    - Maintain a highly technical, objective tone. No fluff or buzzwords.

    STRICT "DO NOT CHANGE" CONSTRAINTS (CRITICAL):
    1. NO HALLUCINATIONS: Do NOT invent, hallucinate, or add new experience, jobs, metrics, or degrees. 
    2. SKILLS: Do NOT add skills the candidate does not have. You may ONLY reframe, reorder, or emphasize the candidate's existing skills to align with the JD.
    3. PREAMBLE: Do NOT alter a single character of the LaTeX preamble (everything before \\begin{{document}}). Return the ENTIRE document from \\documentclass to \\end{{document}}.
    4. FACTS: Do NOT alter employment dates, locations, company names, CGPA, or degree names.
    5. COMMENTS: Leave all commented-out lines (lines starting with %) exactly as they are. Do not un-comment them.
    6. LEADERSHIP SECTION: Do NOT change ANY text in the Leadership section or anything below it. Leave it exactly as provided.
    7. LENGTH LIMIT: Do NOT increase the word count of any existing bullet point by more than 4 words. Keep changes incredibly concise to ensure the CV remains exactly one page.

    JOB DETAILS:
    - Title: {title}
    - Company: {company}
    - Responsibilities: {resp}
    - Requirements: {reqs}

    EVALUATION & REJECTION CRITERIA (CRITICAL):
    1. If the job title or description focuses heavily on QA, SDET (Software Development Engineer in Test), or Test Automation, output <MATCH>NO</MATCH> and stop immediately.
    2. If the role requires 5+ years of experience, output <MATCH>NO</MATCH>.
    3. Otherwise, output <MATCH>YES</MATCH> and proceed.

    BASE DOCUMENTS (LaTeX):
    --- BASE CV ---
    {base_cv}
    
    --- BASE COVER LETTER ---
    {base_cl}

    TASKS IF MATCH IS YES:
    1. Write a compelling 2-sentence summary explaining why the candidate aligns with the role.
    2. Tailor the Base CV text to naturally incorporate keywords from the JD, adhering strictly to the constraints above. 
    3. Tailor the Base Cover Letter to specifically address '{company}' and their requirements.

    CRITICAL LATEX INSTRUCTIONS:
    - ESCAPING: You must heavily escape all special LaTeX characters (%, &, $, _, #) in any newly generated text.
    
    OUTPUT FORMAT:
    - Do NOT wrap your response in markdown blocks (e.g., no ```xml or ```latex). Output raw text only.

    <MATCH>YES or NO</MATCH>
    <SUMMARY>
    Your 2-sentence summary here.
    </SUMMARY>
    <CV>
    % Modified LaTeX CV code here
    </CV>
    <COVER_LETTER>
    % Modified LaTeX Cover Letter code here
    </COVER_LETTER>
    """

    max_retries = 3
    base_delay = 15
    output = None

    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model='gemini-3-flash-preview',
                contents=prompt
            )
            output = response.text
            
            if hasattr(response, 'usage_metadata') and response.usage_metadata:
                print(f"   ↳ Tokens Used: {response.usage_metadata.prompt_token_count} (In) / {response.usage_metadata.candidates_token_count} (Out)")
            
            break
            
        except Exception as e:
            error_msg = str(e).upper()
            if "503" in error_msg or "429" in error_msg or "UNAVAILABLE" in error_msg:
                if attempt < max_retries - 1:
                    sleep_time = base_delay * (2 ** attempt) # 15s, then 30s
                    print(f"   ↳ API Busy (503/429). Retrying in {sleep_time}s... (Attempt {attempt + 1}/{max_retries})")
                    time.sleep(sleep_time)
                else:
                    print(f"   ↳ Gemini API Error: Max retries reached. {e}")
                    return None
            else:
                print(f"   ↳ Gemini API Error: {e}")
                return None

    if not output:
        return None

    is_match = "<MATCH>YES</MATCH>" in output.upper()
    
    if not is_match:
        return None

    try:
        summary_match = re.search(r'<SUMMARY>(.*?)</SUMMARY>', output, re.DOTALL)
        cv_match = re.search(r'<CV>(.*?)</CV>', output, re.DOTALL)
        cl_match = re.search(r'<COVER_LETTER>(.*?)</COVER_LETTER>', output, re.DOTALL)
        
        if not (summary_match and cv_match and cl_match):
            print("   ↳ Error: Missing one or more required XML tags in LLM output.")
            return None

        summary = summary_match.group(1).strip()
        cv_latex_raw = cv_match.group(1)
        cl_latex_raw = cl_match.group(1)
        
        cv_latex = clean_latex_output(cv_latex_raw)
        cl_latex = clean_latex_output(cl_latex_raw)

        cv_latex = sanitize_latex(cv_latex)
        cl_latex = sanitize_latex(cl_latex)

        return {"summary": summary, "cv": cv_latex, "cl": cl_latex}
    except Exception as e:
        print(f"  ↳ Error parsing LLM output: {e}")
        return None

def compile_pdf(tex_string, filename_base):
    tex_filename = f"{filename_base}.tex"
    pdf_filename = f"{filename_base}.pdf"
    
    with open(tex_filename, "w", encoding="utf-8") as f:
        f.write(tex_string)
        
    try:
        print(f"   ↳ Compiling {tex_filename}...")
        result = subprocess.run(
            ["tectonic", tex_filename], 
            check=True, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE,
            text=True
        )
        return pdf_filename
    except FileNotFoundError:
        print("   ↳ System Error: 'tectonic' is not installed or not in PATH.")
        return None
    except subprocess.CalledProcessError as e:
        print(f"   ↳ LaTeX Compilation Failed for {tex_filename}.")
        print(f"   ↳ Tectonic Error Output:\n{e.stderr}")
        return None

def send_email(job_title, apply_link, summary, cv_pdf, cl_pdf, cv_tex, cl_tex):
    msg = EmailMessage()
    msg['Subject'] = f"Automated Job Match: {job_title}"
    msg['From'] = GMAIL_USER
    msg['To'] = GMAIL_USER 
    
    body = f"""
    New Job Match Found!
    
    Job Title: {job_title}
    Apply Link: {apply_link}
    
    Match Summary:
    {summary}
    
    The tailored CV and Cover Letter are attached. 
    Note: If a PDF is missing, compilation failed due to unescaped LaTeX characters. Use the provided .tex files to compile manually.
    """
    msg.set_content(body)
    
    for file_path in [cv_pdf, cl_pdf, cv_tex, cl_tex]:
        if file_path and os.path.exists(file_path):
            with open(file_path, 'rb') as f:
                file_data = f.read()
            
            if file_path.endswith('.pdf'):
                msg.add_attachment(file_data, maintype='application', subtype='pdf', filename=os.path.basename(file_path))
            elif file_path.endswith('.tex'):
                msg.add_attachment(file_data, maintype='text', subtype='plain', filename=os.path.basename(file_path))

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            smtp.send_message(msg)
        print(f"   ↳ Successfully emailed application assets for {job_title}")
    except Exception as e:
        print(f"   ↳ Failed to send email: {e}")

if __name__ == "__main__":
    cv_content = os.getenv("BASE_CV_TEX")
    cl_content = os.getenv("BASE_CL_TEX")

    if not cv_content:
        try:
            with open("cv.tex", "r", encoding="utf-8") as f:
                cv_content = f.read()
        except FileNotFoundError:
            pass

    if not cl_content:
        try:
            with open("cl.tex", "r", encoding="utf-8") as f:
                cl_content = f.read()
        except FileNotFoundError:
            pass

    if not cv_content or not cl_content:
        print("Error: Could not find base templates. Please set BASE_CV_TEX/BASE_CL_TEX in your .env/Secrets, or ensure cv.tex and cl.tex exist locally.")
        exit(1)

    BASE_CV_TEX = cv_content
    BASE_CL_TEX = cl_content

    raw_jobs = fetch_jobs()
    if isinstance(raw_jobs, dict):
        raw_jobs = raw_jobs.get("data", [])
    
    print(f"Initial raw jobs fetched: {len(raw_jobs)}")
    print("-" * 50)
    
    candidate_jobs = []
    target_skills = ["java", "python", "c++"]
    
    for job in raw_jobs:
        job_title = job.get("title", "Unknown Role")
        org_name = job.get("organization", "Unknown Company")
        
        raw_skills = job.get("ai_key_skills") or []
        skills = [skill.lower() for skill in raw_skills]
        
        raw_exp = job.get("ai_experience_level") or ""
        exp_level = str(raw_exp)
        
        if "10+" in exp_level or "5-10" in exp_level:
            print(f"[PRE-FILTER] Dropped: {job_title} at {org_name} | Reason: Experience Level '{exp_level}' too high.")
            continue
            
        if not any(skill in skills for skill in target_skills):
            print(f"[PRE-FILTER] Dropped: {job_title} at {org_name} | Reason: None of {target_skills} found in skills list ({skills}).")
            continue
            
        candidate_jobs.append(job)
        print(f"[PRE-FILTER] Accepted: {job_title} at {org_name}")

    print("-" * 50)
    print(f"Pre-filtering complete. {len(candidate_jobs)} targeted jobs remaining.\n")

    for job in candidate_jobs: 
        title = job.get("title", "Unknown Role")
        org = job.get("organization", "Unknown Company")
        url = job.get("url", "No link provided")
        
        print(f"Evaluating: {title} at {org}...")
        tailored_assets = evaluate_and_tailor(job, BASE_CV_TEX, BASE_CL_TEX) 
        
        if tailored_assets:
            print("   ↳ Match confirmed! Generating files...")
            
            safe_org = re.sub(r'[^a-zA-Z0-9]', '_', org)
            current_cv_name = f"{CV_BASE_NAME}_{safe_org}"
            current_cl_name = f"{CL_BASE_NAME}_{safe_org}"

            cv_pdf = compile_pdf(tailored_assets['cv'], current_cv_name)
            cl_pdf = compile_pdf(tailored_assets['cl'], current_cl_name)
            
            send_email(
                title, 
                url, 
                tailored_assets['summary'], 
                cv_pdf,
                cl_pdf,
                f"{current_cv_name}.tex", 
                f"{current_cl_name}.tex"
            )
            
            if not cv_pdf or not cl_pdf:
                print("   ↳ Notice: PDF compilation failed, but .tex files were emailed.")
                
        else:
            print("   ↳ LLM determined this is not a strong match. Skipping.")
        print("-" * 40)
        time.sleep(4)
