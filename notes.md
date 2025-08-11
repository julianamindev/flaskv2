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

https://www.youtube.com/watch?v=oQ5UfJqW5Jo
NeuralNine video - can find here downloading files (excel and csv)

-----

Don't forget to check templates html files if debugging 404 errors.
Might have forgotten to change values in default bootstrap code.

-----

Flask-WTF

class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])

The html fields should have:
<input name="username" ... >
<input name="password" ... >

If the name="..." doesn't match the field names in the Python form, then the values won't bind to the form fields

-----

flash messages gets carried to the next route which renders it if it isn't consumed

-----

if form.validate_on_submit():
    user = User.query.filter_by(username=form.username.data).first()
    if user and bcrypt.check_password_hash(user.password, form.password.data):
        login_user(user)
        return redirect(url_for('main.home'))

What happens if the form is valid but the user is None or password is wrong?

- validate_on_submit() returns True
- You check user and password
- They fail, but you don't do anything
- So the flow falls through to:

return render_template('login.html', form=form)

Which means the response is served on a POST, and that's why the refresh triggers a resubmission warning

Solution: treat bad credentials as a failure case and redirect just like validation errors.


-----

if using anchor tags with href, it's by default a GET request

-----

when redirecting to logout, especially with session timeouts:

added this in create_app()

    # Prevent caching of all pages, including login
    @app.after_request
    def add_no_cache_headers(response):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

this prevents the CSRF token mismatch when logging in

-----

The CSRF Mismatch Problem (Root Cause)
When Flask renders a form (e.g., login), Flask-WTF generates a CSRF token and stores it in the session.

The CSRF token is also rendered into the form via {{ form.hidden_tag() }}.

But if the session expires (e.g., from inactivity), the CSRF token in the session is lost.

If the browser submits a stale login form (from a cached page), it includes an old CSRF token — which no longer matches the session’s CSRF token (or the session doesn't exist at all).

This causes Flask-WTF to raise a CSRF mismatch error.

-----

app_log (human): page views, counts, branch decisions, timings.
audit (JSON): “who did what to which resource and did it succeed?” (login/logout, CRUD, permissions, session timeout, etc.).
error (human): unexpected exceptions with exc_info=True.