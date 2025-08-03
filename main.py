from flask import Flask, render_template

app = Flask(__name__)


@app.route("/")
def start():
    return render_template("start.html")

@app.route("/other")
def other():
    return render_template("other.html")

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5555, debug=True)
