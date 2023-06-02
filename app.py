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
    # Analizar el cuerpo HTML utilizando BeautifulSoup
    soup = BeautifulSoup(latest_body, 'html.parser')

    # Encontrar el elemento 'blockquote'
    blockquote = soup.find('blockquote')
    if blockquote:
        # Si se encuentra un 'blockquote', buscar el elemento anterior más cercano que sea 'blockquote', 'div' o 'p'
        latest_message = blockquote.find_previous(['blockquote', 'div', 'p'])
    else:
        # Si no se encuentra un 'blockquote', utilizar el propio 'soup'
        latest_message = soup

    # Eliminar los elementos 'style' y 'script' del mensaje más reciente
    for elem in latest_message(['style', 'script']):
        elem.decompose()

    # Obtener el contenido de texto del mensaje más reciente, separado por espacios y sin espacios en los extremos
    text_content = latest_message.get_text(separator=' ', strip=True)

    # Escapar el dominio del correo electrónico del remitente para buscar coincidencias en el texto
    sender_domain_regex = re.escape(sender_email_domain)
    match = re.search(sender_domain_regex, text_content)

    # Verificar si hay una coincidencia o si la longitud del texto alcanza los 1500 caracteres
    if match is not None or len(text_content) >= 1500:
        # Si se cumple alguna de las condiciones, eliminar el contenido a partir de los 1500 caracteres
        text_content = text_content[:1500].strip()

    return text_content


from datetime import datetime

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

    # Convert the sent_date to a datetime object
    sent_date_datetime = datetime.strptime(sent_date, "%a, %d %b %Y %H:%M:%S %z")

    # Format the sent_date as a string in ISO 8601 format
    sent_date_formatted = sent_date_datetime.isoformat()

    recipient_emails = re.findall(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', recipients)
    recipients_email = ', '.join(recipient_emails)

    return sender_email, recipients_email, subject, latest_body, sent_date_formatted


def summarize_email(email_text):
    latest_body = email_text
    model_engine = "text-davinci-002"

    prompt = (
        "[no prose] [Output only JSON] 1.Summary: Make a summary the following email in 25 words. 2.Sentiment: Get the text sentiment. 3.Keywords: Extract 5 keywords:\n\n"
        "{text_content}\n\n"
    )

    response = openai.Completion.create(
        engine=model_engine,
        prompt=prompt.format(text_content=latest_body),
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
    email_file = request.files.get('email')  # Retrieve the file with any name

    if email_file is None:
        return jsonify({'error': 'No email file found'})

    file_type = os.path.splitext(email_file.filename)[1][1:].lower()

    file_path = os.path.join(UPLOAD_FOLDER, secure_filename(email_file.filename))
    email_file.save(file_path)

    sender, recipients, subject, latest_body, sent_date = read_email(file_path, file_type)

    # Call the summarize_email function with the latest_body as the argument
    summary = summarize_email(latest_body)

    response = {
        'sender': sender,
        'recipients': recipients,
        'subject': subject,
        'body': latest_body,
        'sent_date': sent_date,
        'summary': summary
    }

    # Delete the email file from the temp folder
    os.remove(file_path)

    # Return the response as JSON
    return jsonify(response), 200




if __name__ == '__main__':
    app.run()

