import flask
import quart

def apply():
    # Patch flask object to avoid rewriting Dash code. Alternative, we could rewrite it.
    flask.g = quart.g
    flask.has_request_context = quart.has_request_context