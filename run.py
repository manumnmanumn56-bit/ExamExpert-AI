# run.py
# This is the starting point of the ExamExpert AI application.

from flask import Flask   # Flask is the web framework

app = Flask(__name__)     # Create the application object

@app.route("/")           # When someone visits the home page "/"...
def home():
    # ...show this text in the browser
    return "<h1>ExamExpert AI is running!</h1><p>Week 1 setup complete.</p>"

if __name__ == "__main__":
    app.run(debug=True)   # debug=True shows helpful errors while developing