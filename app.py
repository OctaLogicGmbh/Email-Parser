import os
import json
from flask import Flask, request, jsonify
from werkzeug.utils import secure_filename
import openai
import extract_msg
from mailparser import MailParser
from bs4 import BeautifulSoup
import re
import email
import email.policy

UPLOAD_FOLDER = './uploads'
TEMP_FOLDER = './temp'

# Ensure the upload folder exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(TEMP_FOLDER, exist_ok=True)

app = Flask(__name__)
openai.api_key = "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"

def extract_latest_body(latest_body, sender_email_domain):
    soup = BeautifulSoup(latest_body, 'html.parser')

    blockquote = soup.find('blockquote')
    if blockquote:
        latest_message = blockquote.find_previous(['blockquote', 'div', 'p'])
    else:
        latest_message = soup

    for elem in latest_message(['style', 'script']):
        elem.decompose()

    text_content = latest_message.get_text(separator=' ', strip=True)

    sender_domain_regex = re.escape(sender_email_domain)
    match = re.search(sender_domain_regex, text_content)

    if match:
        text_content = text_content[:match.start()].strip()
    
    #print(text_content)

    return text_content


def read_email(file_path, file_type):
    if file_type == 'msg':
        msg = extract_msg.Message(file_path)
        sender = msg.sender
        recipients = msg.to
        subject = msg.subject
        sent_date = msg.date
        html_body = msg.body
    else:
        with open(file_path, 'rb') as f:
            mail_parsed = email.message_from_binary_file(f, policy=email.policy.default)

        sender = mail_parsed['From']
        recipients = mail_parsed['To']
        subject = mail_parsed['Subject']
        sent_date = mail_parsed['Date']

        html_body = ""
        for part in mail_parsed.walk():
            if part.get_content_type() == 'text/html':
                html_body = part.get_content()
                break
    
    
    sender_email = re.search(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', sender).group()

    # Extract the domain from the sender's email address
    sender_email_domain = sender_email.split('@')[1]

    # Pass the sender's email domain to the extract_latest_body function
    latest_body = extract_latest_body(html_body, sender_email_domain)
    #print(sender, recipients, subject, latest_body, sent_date, sender_email_domain)

    return sender, recipients, subject, latest_body, sent_date




def summarize_email(email_text):
    latest_body = email_text
    model_engine = "text-davinci-002"

    prompt = (
        "Please summarize the following email, get the text sentiment and extract 5 keywords:\n\n"
        "{text_content}\n\n"
        "Here's an example of what the response should look like:\n\n"
        "{example_data}\n\n"
        "Your summary:"
    )

    example_data = [
        "The email is requesting support to add three names to a list of sellers.",
        "Positive",
        ["TMS", "Inside Sales", "Caroline"]
    ]

    response = openai.Completion.create(
        engine=model_engine,
        prompt=prompt.format(text_content=latest_body, example_data=example_data),
        max_tokens=1024,
        n=1,
        stop=None,
        temperature=0.5,
    )

    if response["choices"][0]["finish_reason"] != "stop":
        raise ValueError("Failed to summarize email: " + response["choices"][0]["text"])

    summary = response["choices"][0]["text"].strip()
    return summary





@app.route('/summarize_email', methods=['POST'])
def process_email():
    email_file = request.files['email']
    file_type = os.path.splitext(email_file.filename)[1][1:].lower()

    file_path = os.path.join(UPLOAD_FOLDER, secure_filename(email_file.filename))
    email_file.save(file_path)

    sender, recipients, subject, latest_body, sent_date = read_email(file_path, file_type)
    print(latest_body)

    # Call the summarize_email function with the latest_body as the argument
    summary = summarize_email(latest_body)
    #print(summary)

    response = {
        'sender': sender,
        'recipients': recipients,
        'subject': subject,
        'body': latest_body,
        'sent_date': sent_date,
        'summary': summary
    }

    # Save the response dictionary as a JSON file
    response_filename = secure_filename(email_file.filename) + '.json'
    response_filepath = os.path.join(TEMP_FOLDER, response_filename)
    with open(response_filepath, 'w') as json_file:
        json.dump(response, json_file, default=str)

    #print(response)

    return jsonify(response)

if __name__ == '__main__':
    app.run()
