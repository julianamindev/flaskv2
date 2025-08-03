@app.route('/add/<num1>/<num2>')
def add(num1, num2):
    return f"{num1} + {num2} = {num1 + num2}"

# {num1 + num2} addition won't work because num1 and num2 are strings.
# You need to type cast them to become numbers (e.g. int(num1)) in the function or
# declare them as int: @app.route('/add/<int:num1>/<int:num2>')

-----

URL: handle_params?x=abc&y=123

@app.route('/handle_params')
def handle_params():
    return f"{request.args}"

request.args is a dictionary where it will store x = abc and y = 123
they can be accessed via request.args.get('x') or request.args['x']

-----

Flask default templates_folder is "templates"

it can be set as app = Flask(__name__, template_folder="template folder")

-----

creating custom filters in Jinja2
anywhere in the routes code:

@app.template_filter('templ_filter_func')
def templ_filter_func(args):
    ... your code
    return x

Call in template:
{{ variable|templ_filter_func }}

-----


