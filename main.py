from async_dash import Dash
from dash import html
from quart import Quart

app = Dash(server=Quart(__name__))
app.layout = html.Div("Hello world!")

if __name__ == '__main__':
    app.run_server(port=8888)
