import dash
import flask
import quart
import mimetypes
import pkgutil
import sys
import asyncio
import inspect

from dash import _validate
from dash._grouping import map_grouping, grouping_len
from dash._utils import inputs_to_dict, split_callback_id, inputs_to_vals
from dash.fingerprint import check_fingerprint
from dash.dash import _default_index
from quart.utils import run_sync


# borrowed from dash-devices
def exception_handler(loop, context):
    if "future" in context:
        task = context["future"]
        exception = context["exception"]
        # Route the exception through sys.excepthook
        sys.excepthook(exception.__class__, exception, exception.__traceback__)


original_dash = dash.Dash


class Dash(original_dash):
    """Dash is a framework for building analytical web applications.
     No JavaScript required.

     If a parameter can be set by an environment variable, that is listed as:
         env: ``DASH_****``
     Values provided here take precedence over environment variables.

     :param name: The name Quart should use for your app. Even if you provide
         your own ``server``, ``name`` will be used to help find assets.
         Typically ``__name__`` (the magic global var, not a string) is the
         best value to use. Default ``'__main__'``, env: ``DASH_APP_NAME``
     :type name: string

     :param server: Sets the Quart server for your app. There are three options:
         ``True`` (default): Dash will create a new server
         ``False``: The server will be added later via ``app.init_app(server)``
             where ``server`` is a ``quart.Quart`` instance.
         ``quart.Quart``: use this pre-existing Quart server.
     :type server: boolean or quart.Quart

     :param assets_folder: a path, relative to the current working directory,
         for extra files to be used in the browser. Default ``'assets'``.
         All .js and .css files will be loaded immediately unless excluded by
         ``assets_ignore``, and other files such as images will be served if
         requested.
     :type assets_folder: string

     :param assets_url_path: The local urls for assets will be:
         ``requests_pathname_prefix + assets_url_path + '/' + asset_path``
         where ``asset_path`` is the path to a file inside ``assets_folder``.
         Default ``'assets'``.
     :type asset_url_path: string

     :param assets_ignore: A regex, as a string to pass to ``re.compile``, for
         assets to omit from immediate loading. Ignored files will still be
         served if specifically requested. You cannot use this to prevent access
         to sensitive files.
     :type assets_ignore: string

     :param assets_external_path: an absolute URL from which to load assets.
         Use with ``serve_locally=False``. assets_external_path is joined
         with assets_url_path to determine the absolute url to the
         asset folder. Dash can still find js and css to automatically load
         if you also keep local copies in your assets folder that Dash can index,
         but external serving can improve performance and reduce load on
         the Dash server.
         env: ``DASH_ASSETS_EXTERNAL_PATH``
     :type assets_external_path: string

     :param include_assets_files: Default ``True``, set to ``False`` to prevent
         immediate loading of any assets. Assets will still be served if
         specifically requested. You cannot use this to prevent access
         to sensitive files. env: ``DASH_INCLUDE_ASSETS_FILES``
     :type include_assets_files: boolean

     :param url_base_pathname: A local URL prefix to use app-wide.
         Default ``'/'``. Both `requests_pathname_prefix` and
         `routes_pathname_prefix` default to `url_base_pathname`.
         env: ``DASH_URL_BASE_PATHNAME``
     :type url_base_pathname: string

     :param requests_pathname_prefix: A local URL prefix for file requests.
         Defaults to `url_base_pathname`, and must end with
         `routes_pathname_prefix`. env: ``DASH_REQUESTS_PATHNAME_PREFIX``
     :type requests_pathname_prefix: string

     :param routes_pathname_prefix: A local URL prefix for JSON requests.
         Defaults to ``url_base_pathname``, and must start and end
         with ``'/'``. env: ``DASH_ROUTES_PATHNAME_PREFIX``
     :type routes_pathname_prefix: string

     :param serve_locally: If ``True`` (default), assets and dependencies
         (Dash and Component js and css) will be served from local URLs.
         If ``False`` we will use CDN links where available.
     :type serve_locally: boolean

     :param compress: Use gzip to compress files and data served by Flask.
         Default ``False``
     :type compress: boolean

     :param meta_tags: html <meta> tags to be added to the index page.
         Each dict should have the attributes and values for one tag, eg:
         ``{'name': 'description', 'content': 'My App'}``
     :type meta_tags: list of dicts

     :param index_string: Override the standard Dash index page.
         Must contain the correct insertion markers to interpolate various
         content into it depending on the app config and components used.
         See https://dash.plotly.com/external-resources for details.
     :type index_string: string

     :param external_scripts: Additional JS files to load with the page.
         Each entry can be a string (the URL) or a dict with ``src`` (the URL)
         and optionally other ``<script>`` tag attributes such as ``integrity``
         and ``crossorigin``.
     :type external_scripts: list of strings or dicts

     :param external_stylesheets: Additional CSS files to load with the page.
         Each entry can be a string (the URL) or a dict with ``href`` (the URL)
         and optionally other ``<link>`` tag attributes such as ``rel``,
         ``integrity`` and ``crossorigin``.
     :type external_stylesheets: list of strings or dicts

     :param suppress_callback_exceptions: Default ``False``: check callbacks to
         ensure referenced IDs exist and props are valid. Set to ``True``
         if your layout is dynamic, to bypass these checks.
         env: ``DASH_SUPPRESS_CALLBACK_EXCEPTIONS``
     :type suppress_callback_exceptions: boolean

     :param prevent_initial_callbacks: Default ``False``: Sets the default value
         of ``prevent_initial_call`` for all callbacks added to the app.
         Normally all callbacks are fired when the associated outputs are first
         added to the page. You can disable this for individual callbacks by
         setting ``prevent_initial_call`` in their definitions, or set it
         ``True`` here in which case you must explicitly set it ``False`` for
         those callbacks you wish to have an initial call. This setting has no
         effect on triggering callbacks when their inputs change later on.

     :param show_undo_redo: Default ``False``, set to ``True`` to enable undo
         and redo buttons for stepping through the history of the app state.
     :type show_undo_redo: boolean

     :param extra_hot_reload_paths: A list of paths to watch for changes, in
         addition to assets and known Python and JS code, if hot reloading is
         enabled.
     :type extra_hot_reload_paths: list of strings

     :param plugins: Extend Dash functionality by passing a list of objects
         with a ``plug`` method, taking a single argument: this app, which will
         be called after the Flask server is attached.
     :type plugins: list of objects

     :param title: Default ``Dash``. Configures the document.title
     (the text that appears in a browser tab).

     :param update_title: Default ``Updating...``. Configures the document.title
     (the text that appears in a browser tab) text when a callback is being run.
     Set to None or '' if you don't want the document.title to change or if you
     want to control the document.title through a separate component or
     clientside callback.

     :param long_callback_manager: Long callback manager instance to support the
     ``@app.long_callback`` decorator. Currently an instance of one of
     ``DiskcacheLongCallbackManager`` or ``CeleryLongCallbackManager``
     """

    def __init__(self,
                 name=None,
                 server=True,
                 assets_folder="assets",
                 assets_url_path="assets",
                 assets_ignore="",
                 assets_external_path=None,
                 eager_loading=False,
                 include_assets_files=True,
                 url_base_pathname=None,
                 requests_pathname_prefix=None,
                 routes_pathname_prefix=None,
                 serve_locally=True,
                 compress=None,
                 meta_tags=None,
                 index_string=_default_index,
                 external_scripts=None,
                 external_stylesheets=None,
                 suppress_callback_exceptions=None,
                 prevent_initial_callbacks=False,
                 show_undo_redo=False,
                 extra_hot_reload_paths=None,
                 plugins=None,
                 title="Dash",
                 update_title="Updating...",
                 long_callback_manager=None,
                 **obsolete):
        super().__init__(name, server, assets_folder, assets_url_path, assets_ignore, assets_external_path,
                         eager_loading, include_assets_files, url_base_pathname, requests_pathname_prefix,
                         routes_pathname_prefix, serve_locally, compress, meta_tags, index_string, external_scripts,
                         external_stylesheets, suppress_callback_exceptions, prevent_initial_callbacks, show_undo_redo,
                         extra_hot_reload_paths, plugins, title, update_title, long_callback_manager, **obsolete)

    async def serve_component_suites(self, package_name, fingerprinted_path):
        path_in_pkg, has_fingerprint = check_fingerprint(fingerprinted_path)

        _validate.validate_js_path(self.registered_paths, package_name, path_in_pkg)

        extension = "." + path_in_pkg.split(".")[-1]
        mimetype = mimetypes.types_map.get(extension, "application/octet-stream")

        package = sys.modules[package_name]
        self.logger.debug(
            "serving -- package: %s[%s] resource: %s => location: %s",
            package_name,
            package.__version__,
            path_in_pkg,
            package.__path__,
        )

        response = quart.Response(
            pkgutil.get_data(package_name, path_in_pkg), mimetype=mimetype
        )

        if has_fingerprint:
            # Fingerprinted resources are good forever (1 year)
            # No need for ETag as the fingerprint changes with each build
            response.cache_control.max_age = 31536000  # 1 year
        else:
            # Non-fingerprinted resources are given an ETag that
            # will be used / check on future requests
            await response.add_etag()
            tag = response.get_etag()[0]

            request_etag = quart.request.headers.get("If-None-Match")

            if '"{}"'.format(tag) == request_etag:
                response = quart.Response("", status=304)

        return response

    async def dispatch(self):
        body = await quart.request.get_json()
        quart.g.inputs_list = inputs = body.get(  # pylint: disable=assigning-non-slot
            "inputs", []
        )
        quart.g.states_list = state = body.get(  # pylint: disable=assigning-non-slot
            "state", []
        )
        output = body["output"]
        outputs_list = body.get("outputs") or split_callback_id(output)
        quart.g.outputs_list = outputs_list  # pylint: disable=assigning-non-slot

        quart.g.input_values = (  # pylint: disable=assigning-non-slot
            input_values
        ) = inputs_to_dict(inputs)
        quart.g.state_values = inputs_to_dict(  # pylint: disable=assigning-non-slot
            state
        )
        changed_props = body.get("changedPropIds", [])
        quart.g.triggered_inputs = [  # pylint: disable=assigning-non-slot
            {"prop_id": x, "value": input_values.get(x)} for x in changed_props
        ]

        response = (
            quart.g.dash_response  # pylint: disable=assigning-non-slot
        ) = quart.Response("", mimetype="application/json")

        args = inputs_to_vals(inputs + state)

        try:
            cb = self.callback_map[output]
            func = cb["callback"]

            # Add args_grouping
            inputs_state_indices = cb["inputs_state_indices"]
            inputs_state = inputs + state
            args_grouping = map_grouping(
                lambda ind: inputs_state[ind], inputs_state_indices
            )
            quart.g.args_grouping = args_grouping  # pylint: disable=assigning-non-slot
            quart.g.using_args_grouping = (  # pylint: disable=assigning-non-slot
                    not isinstance(inputs_state_indices, int)
                    and (
                            inputs_state_indices
                            != list(range(grouping_len(inputs_state_indices)))
                    )
            )

            # Add outputs_grouping
            outputs_indices = cb["outputs_indices"]
            if not isinstance(outputs_list, list):
                flat_outputs = [outputs_list]
            else:
                flat_outputs = outputs_list

            outputs_grouping = map_grouping(
                lambda ind: flat_outputs[ind], outputs_indices
            )
            quart.g.outputs_grouping = (  # pylint: disable=assigning-non-slot
                outputs_grouping
            )
            quart.g.using_outputs_grouping = (  # pylint: disable=assigning-non-slot
                    not isinstance(outputs_indices, int)
                    and outputs_indices != list(range(grouping_len(outputs_indices)))
            )

        except KeyError as missing_callback_function:
            msg = "Callback function not found for output '{}', perhaps you forgot to prepend the '@'?"
            raise KeyError(msg.format(output)) from missing_callback_function
        if inspect.iscoroutinefunction(func):
            output = await func(*args, outputs_list=outputs_list)
        else:
            output = run_sync(func)(*args, outputs_list=outputs_list)
        response.set_data(output)
        return response

    def run_server(self, *args, **kwargs):
        loop = asyncio.get_event_loop()
        loop.set_exception_handler(exception_handler)
        return super().run_server(*args, **kwargs, loop=loop)

    async def serve_layout(self):
        return super().serve_layout()

    async def serve_reload_hash(self):
        return super().serve_reload_hash()

    async def index(self, *args, **kwargs):
        return super().index(*args, **kwargs)

    async def dependencies(self):
        return super().dependencies()

    async def _serve_default_favicon(self):
        return super()._serve_default_favicon()


def apply():
    # Patch flask object to avoid rewriting Dash code. Alternative, we could rewrite it.
    flask.Flask = quart.Quart
    flask.Blueprint = quart.Blueprint
    flask.jsonify = quart.jsonify
    flask.Response = quart.Response
    # Patch dash object. TODO: Will this make dash-extensions work?
    dash.Dash = Dash
