import inspect
import mimetypes
import os
import pkgutil
import sys
import asyncio
import inspect
import json
import plotly.utils
import quart
from dash._grouping import map_grouping
from dash._utils import inputs_to_dict, split_callback_id, inputs_to_vals
from dash.fingerprint import check_fingerprint
from quart_compress import Compress
from quart.utils import run_sync
import dash
import flask
import quart

from functools import wraps

# region Monkey patch of _callback

import dash._callback as cb
from dash._callback import handle_grouped_callback_args, Output, flatten_grouping, make_grouping_by_index, \
    grouping_len, insert_callback, _validate, PreventUpdate, NoUpdate, collections, stringify_id, to_json


def register_callback(
        callback_list, callback_map, config_prevent_initial_callbacks, *_args, **_kwargs
):
    (
        output,
        flat_inputs,
        flat_state,
        inputs_state_indices,
        prevent_initial_call,
    ) = handle_grouped_callback_args(_args, _kwargs)
    if isinstance(output, Output):
        # Insert callback with scalar (non-multi) Output
        insert_output = output
        multi = False
    else:
        # Insert callback as multi Output
        insert_output = flatten_grouping(output)
        multi = True

    output_indices = make_grouping_by_index(output, list(range(grouping_len(output))))
    callback_id = insert_callback(
        callback_list,
        callback_map,
        config_prevent_initial_callbacks,
        insert_output,
        output_indices,
        flat_inputs,
        flat_state,
        inputs_state_indices,
        prevent_initial_call,
    )

    # pylint: disable=too-many-locals
    def wrap_func(func):
        @wraps(func)
        async def add_context(*args, **kwargs):  # ASYNC: Change from def "add_context(*args, **kwargs)"
            output_spec = kwargs.pop("outputs_list")
            _validate.validate_output_spec(insert_output, output_spec, Output)

            func_args, func_kwargs = _validate.validate_and_group_input_args(
                args, inputs_state_indices
            )

            # region ASYNC: Added iscoroutinefunction check

            # don't touch the comment on the next line - used by debugger
            if inspect.iscoroutinefunction(func):
                output_value = await func(
                    *func_args, **func_kwargs
                )  # %% callback invoked %%
            else:
                output_value = func(*func_args, **func_kwargs)  # %% callback invoked %%

            # endregion

            if isinstance(output_value, NoUpdate):
                raise PreventUpdate

            if not multi:
                output_value, output_spec = [output_value], [output_spec]
                flat_output_values = output_value
            else:
                if isinstance(output_value, (list, tuple)):
                    # For multi-output, allow top-level collection to be
                    # list or tuple
                    output_value = list(output_value)

                # Flatten grouping and validate grouping structure
                flat_output_values = flatten_grouping(output_value, output)

            _validate.validate_multi_return(
                output_spec, flat_output_values, callback_id
            )

            component_ids = collections.defaultdict(dict)
            has_update = False
            for val, spec in zip(flat_output_values, output_spec):
                if isinstance(val, NoUpdate):
                    continue
                for vali, speci in (
                        zip(val, spec) if isinstance(spec, list) else [[val, spec]]
                ):
                    if not isinstance(vali, NoUpdate):
                        has_update = True
                        id_str = stringify_id(speci["id"])
                        component_ids[id_str][speci["property"]] = vali

            if not has_update:
                raise PreventUpdate

            response = {"response": component_ids, "multi": True}

            try:
                jsonResponse = to_json(response)
            except TypeError:
                _validate.fail_callback_output(output_value, output)

            return jsonResponse

        callback_map[callback_id]["callback"] = add_context

        return add_context

    return wrap_func


cb.register_callback = register_callback

# endregion

# region Monkey patch of _callback_context

flask.g = quart.g
flask.has_request_context = quart.has_request_context

# endregion

# region Monkey patch of dash

flask.Flask = quart.Quart
flask.Blueprint = quart.Blueprint
flask.jsonify = quart.jsonify
flask.Response = quart.Response


# borrowed from dash-devices
def exception_handler(loop, context):
    if "future" in context:
        task = context["future"]
        exception = context["exception"]
        # Route the exception through sys.excepthook
        sys.excepthook(exception.__class__, exception, exception.__traceback__)


original_dash = dash.Dash

class AsyncDash(original_dash):


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


dash.Dash.serve_component_suites = serve_component_suites


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


dash.Dash.dispatch = dispatch


def run_server(self, *args, **kwargs):
    loop = asyncio.get_event_loop()
    loop.set_exception_handler(exception_handler)
    return run_server_original(self, *args, **kwargs, loop=loop)


run_server_original = dash.Dash.run_server
dash.Dash.run_server = run_server


# Functions below just need mapping to async. Maybe do it in a loop?

async def serve_layout(self):
    return serve_layout_original(self)


serve_layout_original = dash.Dash.serve_layout
dash.Dash.serve_layout = serve_layout


async def serve_reload_hash(self):
    return serve_reload_hash_original(self)


serve_reload_hash_original = dash.Dash.serve_reload_hash
dash.Dash.serve_reload_hash = serve_reload_hash


async def index(self, *args, **kwargs):
    return index_original(self, *args, **kwargs)


index_original = dash.Dash.index
dash.Dash.index = index


async def dependencies(self):
    return dependencies_original(self)


dependencies_original = dash.Dash.dependencies
dash.Dash.dependencies = dependencies


async def _serve_default_favicon(self):
    return _serve_default_favicon_original()


_serve_default_favicon_original = dash.Dash._serve_default_favicon
dash.Dash._serve_default_favicon = _serve_default_favicon

# endregion

from dash import html
from quart import Quart

app = dash.Dash(server=Quart(__name__))
app.layout = html.Div("Hello world!")

if __name__ == '__main__':
    app.run_server(port=8888)
