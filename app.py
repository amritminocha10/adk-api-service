from flask import Flask

app = Flask(__name__)

@app.route('/')
def index():
    return "Welcome to AutoClaim360 ADK API Service"

if __name__ == '__main__':
    app.run(debug=True)