from flask import Flask, request, jsonify, send_file, render_template
from werkzeug.utils import secure_filename
import os
import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
from flask_socketio import SocketIO, emit

ALLOWED_EXTENSIONS = {'csv'}

app = Flask(__name__, template_folder='templates')
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['PROCESSED_FOLDER'] = 'processed'
socketio = SocketIO(app)

if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

if not os.path.exists(app.config['PROCESSED_FOLDER']):
    os.makedirs(app.config['PROCESSED_FOLDER'])

# List to keep track of opened URLs
opened_urls = []

class GeneObject:
    def __init__(self, url, name, description, organism, dataset, sequence):
        self.url = url
        self.name = name
        self.description = description
        self.organism = organism
        self.dataset = dataset
        self.sequence = sequence

def getURLsFromDatabase(filename):
    df = pd.read_csv(filename)
    first_column = df.iloc[:, 0]
    blank_index = first_column[first_column.isnull() | (first_column == '')].index[0]
    result = first_column[:blank_index].tolist()
    return result

def getGeneData(filename, description, organism, dataset):
    urls = getURLsFromDatabase(filename)
    gene_objects = []
    gene_errors = []

    for i in range(len(urls)):
        try:
            gene_objects.append(getCDSfromURL('https://'+urls[i], description, organism, dataset))
            print("--------------------------------")
            print("Progress: " + str(i) + "/" + str(len(urls)-1))
            
            # Send progress update
            socketio.emit('progress', {'progress': (i + 1) / len(urls) * 100})
        except Exception as e:
            gene_objects.append(GeneObject('https://'+urls[i], "Error", description, organism, "Empty?", dataset))
            gene_errors.append(i)
            print("Error @ " + str(i))
            socketio.emit('progress', {'progress': (i + 1) / len(urls) * 100})

    data = [
        {
            'URL': gene.url,
            'Name': gene.name,
            'Description': gene.description,
            'Organism': gene.organism,
            'Dataset': gene.dataset,
            'Sequence': gene.sequence
        }
        for gene in gene_objects
    ]

    df = pd.DataFrame(data)
    df.to_csv(filename[:-4] + ' Output.csv', index=False)
    
    output_path = os.path.join(app.config['PROCESSED_FOLDER'], 'output.csv')

    if not os.path.exists(app.config['PROCESSED_FOLDER']):
        os.makedirs(app.config['PROCESSED_FOLDER'])

    df.to_csv(output_path, index=False)

    print("CSV file 'output.csv' has been created successfully.")
    with open(os.path.join(app.config['PROCESSED_FOLDER'], 'opened_urls.txt'), 'w') as f:
        for url in opened_urls:
            f.write(url + '\n')
    print("Opened URLs have been logged to 'opened_urls.txt'.")
    return output_path

def getCDSfromURL(url, description, organism, dataset):
    startWebDriver()
    clickTranscriptDNA(url)
    geneName = getGeneName()
    cdsText = getCDS()
    print(geneName)
    print(cdsText)
    return GeneObject(url, geneName, description, organism, dataset, cdsText)

def startWebDriver():
    global driver
    options = Options()
    options.add_argument("--disable-infobars")
    options.add_argument("--headless")
    driver = webdriver.Chrome(options=options)

def getGeneName():
    global driver
    element = WebDriverWait(driver, 10).until(
        EC.visibility_of_element_located((By.XPATH, '//*[@id="content"]/div/div[1]/dl/dd[1]'))
    )
    name = element.text
    return name.split("\n")[0]

def clickTranscriptDNA(url):
    global driver
    driver.get(url)
    opened_urls.append(driver.current_url)
    time.sleep(10)
    element = driver.find_element(By.XPATH, '//*[@id="track_Transcripts"]/canvas')
    element.click()
    opened_urls.append(driver.current_url)
    print(driver.current_url)

def getCDS():
    global driver
    element = WebDriverWait(driver, 15).until(
        EC.element_to_be_clickable((By.XPATH, '//*[@id="content"]/div/div[4]/div[4]/label/div/div/a/button/span'))
    )
    element.click()
    element = WebDriverWait(driver, 15).until(
        EC.visibility_of_element_located((By.XPATH, '//*[@id="content"]/div/div/div/div/form/fieldset/textarea'))
    )
    sequence = element.text
    return sequence.split("\n")[1]

def allowed_file(filename):
    return '.' in filename and \
        filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files['file']
    
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        description = request.form['description']
        organism = request.form['organism']
        dataset = request.form['dataset']

        output_file = getGeneData(filepath, description, organism, dataset)
        return send_file(output_file, as_attachment=True)

if __name__ == '__main__':
    socketio.run(app, debug=True)
