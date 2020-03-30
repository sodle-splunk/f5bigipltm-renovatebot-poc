# File: f5bigipltm_connector.py
#
# Copyright (c) 2019-2020 Splunk Inc.
#
# SPLUNK CONFIDENTIAL - Use or disclosure of this material in whole or in part
# without a valid written license from Splunk Inc. is PROHIBITED.

# Phantom App imports
import phantom.app as phantom
from phantom.base_connector import BaseConnector
from phantom.action_result import ActionResult

# Usage of the consts file is recommended
import requests
import json
import ipaddress
import sys
from bs4 import BeautifulSoup, UnicodeDammit


class RetVal(tuple):
    def __new__(cls, val1, val2=None):
        return tuple.__new__(RetVal, (val1, val2))


class F5BigipLtmConnector(BaseConnector):

    def __init__(self):

        # Call the BaseConnectors init first
        super(F5BigipLtmConnector, self).__init__()

        self._auth = None
        self._state = None
        self._base_url = None

    def _process_empty_response(self, response, action_result):

        # The JSON Content-Type data can also come here if r.text is empty, hence,
        # the exposed range for valid success scenarios in the response
        # processing of JSON also should be considered here.
        if 200 <= response.status_code < 399:
            return RetVal(phantom.APP_SUCCESS, {})

        return RetVal(action_result.set_status(phantom.APP_ERROR, "Empty response and no information in the header"), None)

    def _process_html_response(self, response, action_result):

        # An html response, treat it like an error
        status_code = response.status_code

        if (status_code == 200):
            return RetVal(phantom.APP_SUCCESS, response.text)

        try:
            soup = BeautifulSoup(response.text, "html.parser")
            if soup.body and soup.body.text:
                error_text = soup.body.text
            else:
                error_text = soup.text
            split_lines = error_text.split('\n')
            split_lines = [x.strip() for x in split_lines if x.strip()]
            error_text = '\n'.join(split_lines)
        except:
            error_text = "Cannot parse error details"

        message = "Status Code: {0}. Data from server:\n{1}\n".format(status_code,
                self._handle_py_ver_compat_for_input_str(self._python_version, error_text))

        try:
            message = message.replace(u'{', '{{').replace(u'}', '}}')
        except:
            message = message.replace('{', '{{').replace('}', '}}')

        return RetVal(action_result.set_status(phantom.APP_ERROR, message), None)

    def _process_json_response(self, r, action_result):

        # Try a json parse
        try:
            resp_json = r.json()
        except Exception as e:
            return RetVal(action_result.set_status(phantom.APP_ERROR, "Unable to parse JSON response. Error: {0}".format(str(e))), None)

        # Please specify the status codes here
        if 200 <= r.status_code < 399:
            return RetVal(phantom.APP_SUCCESS, resp_json)

        try:
            if resp_json and (resp_json.get("code") or resp_json.get("message")):
                if resp_json.get("message"):
                    error_msg = self._handle_py_ver_compat_for_input_str(self._python_version, resp_json.get("message"))
                else:
                    error_msg = "Unable to find 'message' key in the JSON error response"
                message = "Error occurred while making the request. Status Code: {0}. Response Code: {1}. Message from server: {2}".format(
                                                                                                                    r.status_code, resp_json.get("code"), error_msg)
            else:
                # You should process the error returned in the json
                try:
                    error_msg = r.text.encode('utf-8').replace(u'{', '{{').replace(u'}', '}}')
                except:
                    error_msg = r.text.encode('utf-8').replace('{', '{{').replace('}', '}}')

                error_msg = self._handle_py_ver_compat_for_input_str(self._python_version, error_msg)
                message = "Error from server. Status Code: {0} Data from server: {1}".format(
                        r.status_code, error_msg)
        except Exception as e:
            _, error_msg = self._get_error_message_from_exception(e)
            message = "Unknown error occurred while processing the output response from the server. Status Code: {0}. Data from server: {1}".format(r.status_code, error_msg)

        return RetVal(action_result.set_status(phantom.APP_ERROR, message), None)

    def _process_response(self, r, action_result):

        # store the r_text in debug data, it will get dumped in the logs if the action fails
        if hasattr(action_result, 'add_debug_data'):
            action_result.add_debug_data({'r_status_code': r.status_code})
            action_result.add_debug_data({'r_text': r.text})
            action_result.add_debug_data({'r_headers': r.headers})

        # Process each 'Content-Type' of response separately

        # Process a json response
        if 'json' in r.headers.get('Content-Type', ''):
            if not r.text:
                self.debug_print("Processing the JSON Content-Type response with 'process_empty_response' due to empty 'r.text' value")
                return self._process_empty_response(r, action_result)
            else:
                return self._process_json_response(r, action_result)

        # Process an HTML response, Do this no matter what the api talks.
        # There is a high chance of a PROXY in between phantom and the rest of
        # world, in case of errors, PROXY's return HTML, this function parses
        # the error and adds it to the action_result.
        if 'html' in r.headers.get('Content-Type', ''):
            return self._process_html_response(r, action_result)

        # it's not content-type that is to be parsed, handle an empty response
        if not r.text:
            return self._process_empty_response(r, action_result)

        # everything else is actually an error at this point
        message = "Can't process response from server. Status Code: {0} Data from server: {1}".format(
                r.status_code, r.text.replace('{', '{{').replace('}', '}}'))

        return RetVal(action_result.set_status(phantom.APP_ERROR, message), None)

    @staticmethod
    def _handle_py_ver_compat_for_input_str(python_version, input_str):
        """
        This method returns the encoded|original string based on the Python version.

        :param python_version: Information of the Python version
        :param input_str: Input string to be processed
        :return: input_str (Processed input string based on following logic 'input_str - Python 3; encoded input_str - Python 2')
        """

        if python_version == 2:
            input_str = UnicodeDammit(input_str).unicode_markup.encode('utf-8')

        return input_str

    def _get_error_message_from_exception(self, e):
        """ This method is used to get appropriate error message from the exception.
        :param e: Exception object
        :return: error message
        """

        try:
            if e.args:
                if len(e.args) > 1:
                    error_code = e.args[0]
                    error_msg = e.args[1]
                elif len(e.args) == 1:
                    error_code = "Error code unavailable"
                    error_msg = e.args[0]
            else:
                error_code = "Error code unavailable"
                error_msg = "Unknown error occurred. Please check the asset configuration and|or action parameters."
        except:
            error_code = "Error code unavailable"
            error_msg = "Unknown error occurred. Please check the asset configuration and|or action parameters."

        try:
            error_msg = self._handle_py_ver_compat_for_input_str(self._python_version, error_msg)
        except TypeError:
            error_msg = "Error occurred while connecting to the F5 server. Please check the asset configuration and|or the action parameters."
        except:
            error_msg = "Unknown error occurred. Please check the asset configuration and|or action parameters."

        return error_code, error_msg

    def _make_rest_call(self, endpoint, action_result, method="get", data=None, **kwargs):

        config = self.get_config()

        resp_json = None

        # Handling for default 'latin-1' encoding in make_rest_call data=json_str
        if data:
            if self._python_version == 3:
                data = data.encode('UTF-8')

        try:
            request_func = getattr(requests, method)
        except AttributeError:
            return RetVal(action_result.set_status(phantom.APP_ERROR, "Invalid method: {0}".format(method)), resp_json)

        # Create a URL to connect to
        try:
            url = "{}{}".format(self._base_url, endpoint)
        except Exception as e:
            error_code, error_msg = self._get_error_message_from_exception(e)
            return RetVal(action_result.set_status(phantom.APP_ERROR, "Unable to parse JSON response. Error Code: {0}. Error Message: {1}".format(error_code, error_msg)), None)

        # To avoid UnicodeDecodeError in Phantom 4.8 python 2 version if any unicode character is present in URL
        if self._python_version == 2:
            url = url.decode('utf-8')

        try:
            r = request_func(
                            url,
                            auth=self._auth,
                            verify=config.get('verify_server_cert', False),
                            data=data,
                            **kwargs)
        except Exception as e:
            error_code, error_msg = self._get_error_message_from_exception(e)
            return RetVal(action_result.set_status(phantom.APP_ERROR, "Error occurred while making the REST call to the F5 server. Error Code: {0}. Error Message: {1}".format(
                            error_code, error_msg)), None)

        return self._process_response(r, action_result)

    def _handle_test_connectivity(self, param):

        self.save_progress("In action handler for: {0}".format(self.get_action_identifier()))

        action_result = self.add_action_result(ActionResult(dict(param)))

        self.save_progress("Querying info about F5 BIG-IP LTM instance to test connectivity")

        ret_val, response = self._make_rest_call('/mgmt/tm/ltm', action_result, params=None, headers=None)

        if (phantom.is_fail(ret_val)):
            self.save_progress("Test Connectivity Failed")
            return action_result.get_status()

        # Return success
        self.save_progress("Test Connectivity Passed")
        return action_result.set_status(phantom.APP_SUCCESS)

    def _handle_remove_node(self, param):

        self.save_progress("In action handler for: {0}".format(self.get_action_identifier()))

        action_result = self.add_action_result(ActionResult(dict(param)))

        pool_name = self._handle_py_ver_compat_for_input_str(self._python_version, param['pool_name'])
        node_name = self._handle_py_ver_compat_for_input_str(self._python_version, param['node_name'])
        port = param['port']

        try:
            int(port)
        except:
            return action_result.set_status(phantom.APP_ERROR, "Please enter a valid integer in 'port' parameter")

        if not 0 <= int(port) <= 65535:
            return action_result.set_status(phantom.APP_ERROR, "Please enter the port in range of 0 to 65535")

        # make rest call
        ret_val, response = self._make_rest_call('/mgmt/tm/ltm/pool/{0}/members/{1}:{2}'.format(pool_name, node_name, port), action_result, method="delete")

        if (phantom.is_fail(ret_val)):
            return action_result.get_status()

        action_result.add_data({})

        summary = action_result.update_summary({})
        summary['node_name'] = pool_name
        summary['port'] = port
        summary['pool_name'] = pool_name

        return action_result.set_status(phantom.APP_SUCCESS, "Node successfully removed from pool")

    def _handle_add_node(self, param):

        self.save_progress("In action handler for: {0}".format(self.get_action_identifier()))

        action_result = self.add_action_result(ActionResult(dict(param)))
        node_name = self._handle_py_ver_compat_for_input_str(self._python_version, param['node_name']).replace('\\', '\\\\').replace('"', '\\"')
        port = param['port']
        partition_name = self._handle_py_ver_compat_for_input_str(self._python_version, param['partition_name']).replace('\\', '\\\\').replace('"', '\\"')
        pool_name = self._handle_py_ver_compat_for_input_str(self._python_version, param['pool_name']).replace('\\', '\\\\').replace('"', '\\"')

        try:
            int(port)
        except:
            return action_result.set_status(phantom.APP_ERROR, "Please enter a valid integer in 'port' parameter")

        if not 0 <= int(port) <= 65535:
            return action_result.set_status(phantom.APP_ERROR, "Please enter the port in range of 0 to 65535")

        json_str = '{{"name": "/{0}/{1}:{2}"}}'.format(partition_name, node_name, port)

        # make rest call
        ret_val, response = self._make_rest_call('/mgmt/tm/ltm/pool/{0}/members'.format(pool_name),
                                                     action_result, method="post", data=json_str)

        if (phantom.is_fail(ret_val)):
            return action_result.get_status()

        action_result.add_data(response)

        summary = action_result.update_summary({})
        summary['node_name'] = response.get('name')
        summary['port'] = port
        summary['pool_name'] = pool_name

        return action_result.set_status(phantom.APP_SUCCESS, "Node successfully added to pool")

    def _is_ip(self, input_ip_address):
        """ Function that checks given address and return True if address is valid IPv4 or IPV6 address.

        :param input_ip_address: IP address
        :return: status (success/failure)
        """

        ip_address_input = UnicodeDammit(input_ip_address).unicode_markup.encode('UTF-8').decode('UTF-8')

        try:
            ipaddress.ip_address(ip_address_input)
        except:
            return False

        return True

    def _paginator(self, endpoint, action_result, payload=None, limit=None):

        items_list = list()
        f5_default_limit = 100

        if not payload:
            payload = dict()

        payload['$skip'] = 0
        payload['$top'] = f5_default_limit

        while True:
            ret_val, items = self._make_rest_call(endpoint, action_result, params=payload)

            if phantom.is_fail(ret_val) or items.get("items") is None:
                return None

            items_list.extend(items.get("items"))

            if limit and len(items_list) >= limit:
                return items_list[:limit]

            if len(items.get("items")) < f5_default_limit:
                break

            payload['$skip'] = payload['$skip'] + f5_default_limit

        return items_list

    def _handle_create_node(self, param):

        self.save_progress("In action handler for: {0}".format(self.get_action_identifier()))

        action_result = self.add_action_result(ActionResult(dict(param)))

        node = self._handle_py_ver_compat_for_input_str(self._python_version, param['node_name']).replace('\\', '\\\\').replace('"', '\\"')
        partition = self._handle_py_ver_compat_for_input_str(self._python_version, param['partition_name']).replace('\\', '\\\\').replace('"', '\\"')
        address = param['ip_address']

        json_str = '{{"name": "{}", "partition": "{}", "address": "{}"}}'.format(node, partition, address)

        # make rest call
        ret_val, response = self._make_rest_call('/mgmt/tm/ltm/node', action_result, method="post", data=json_str)

        if (phantom.is_fail(ret_val)):
            return action_result.get_status()

        action_result.add_data(response)

        summary = action_result.update_summary({})
        summary['node_name'] = response.get('name')

        return action_result.set_status(phantom.APP_SUCCESS, "Node successfully created")

    def _handle_delete_node(self, param):
        self.save_progress("In action handler for: {0}".format(self.get_action_identifier()))

        action_result = self.add_action_result(ActionResult(dict(param)))

        node_name = self._handle_py_ver_compat_for_input_str(self._python_version, param['node_name'])
        # make rest call
        ret_val, response = self._make_rest_call('/mgmt/tm/ltm/node/{0}'.format(node_name), action_result, method="delete")

        if (phantom.is_fail(ret_val)):
            return action_result.get_status()

        action_result.add_data({})

        summary = action_result.update_summary({})
        summary['node_name'] = node_name

        return action_result.set_status(phantom.APP_SUCCESS, "Successfully deleted node")

    def _handle_disable_node(self, param):

        self.save_progress("In action handler for: {0}".format(self.get_action_identifier()))

        action_result = self.add_action_result(ActionResult(dict(param)))

        node_name = self._handle_py_ver_compat_for_input_str(self._python_version, param['node_name'])
        param['session'] = 'user-disabled'

        # make rest call
        ret_val, response = self._make_rest_call('/mgmt/tm/ltm/node/{0}'.format(node_name), action_result, method="patch", json={'session': 'user-disabled'})

        if (phantom.is_fail(ret_val)):
            return action_result.get_status()

        # Add the response into the data section
        action_result.add_data(response)

        summary = action_result.update_summary({})
        summary['node_name'] = node_name

        return action_result.set_status(phantom.APP_SUCCESS, "Successfully disabled node")

    def _handle_enable_node(self, param):

        self.save_progress("In action handler for: {0}".format(self.get_action_identifier()))

        action_result = self.add_action_result(ActionResult(dict(param)))

        node_name = self._handle_py_ver_compat_for_input_str(self._python_version, param['node_name'])
        param['session'] = 'user-enabled'

        # make rest call
        ret_val, response = self._make_rest_call('/mgmt/tm/ltm/node/{0}'.format(node_name), action_result, method="patch", json={'session': 'user-enabled'})

        if (phantom.is_fail(ret_val)):
            return action_result.get_status()

        # Add the response into the data section
        action_result.add_data(response)

        summary = action_result.update_summary({})
        summary['node_name'] = node_name

        return action_result.set_status(phantom.APP_SUCCESS, "Successfully enabled node")

    def _handle_describe_node(self, param):

        self.save_progress("In action handler for: {0}".format(self.get_action_identifier()))

        action_result = self.add_action_result(ActionResult(dict(param)))

        node_name = self._handle_py_ver_compat_for_input_str(self._python_version, param['node_name'])

        # make rest call
        ret_val, response = self._make_rest_call('/mgmt/tm/ltm/node/{0}'.format(node_name), action_result)

        if (phantom.is_fail(ret_val)):
            return action_result.get_status()

        action_result.add_data(response)

        summary = action_result.update_summary({})
        summary['state'] = response.get('state')

        return action_result.set_status(phantom.APP_SUCCESS)

    def _handle_list_nodes(self, param):

        self.save_progress("In action handler for: {0}".format(self.get_action_identifier()))

        action_result = self.add_action_result(ActionResult(dict(param)))

        max_results = param.get("max_results")

        try:
            if max_results is not None and int(max_results) <= 0:
                return action_result.set_status(phantom.APP_ERROR, "Please provide a non-zero positive integer in 'max results' parameter")
        except:
            return action_result.set_status(phantom.APP_ERROR, "Please provide a non-zero positive integer in 'max results' parameter")

        response = self._paginator('/mgmt/tm/ltm/node', action_result, limit=max_results)

        if response is None:
            return action_result.get_status()

        node_names = []

        for item in response:
            action_result.add_data(item)
            if 'name' in item:
                node_names.append(item['name'])

        summary = action_result.update_summary({})
        summary['num_nodes'] = len(action_result.get_data())
        summary['node_names'] = ', '.join(node_names)

        return action_result.set_status(phantom.APP_SUCCESS)

    def _handle_list_pools(self, param):

        self.save_progress("In action handler for: {0}".format(self.get_action_identifier()))

        action_result = self.add_action_result(ActionResult(dict(param)))

        max_results = param.get("max_results")

        try:
            if max_results is not None and int(max_results) <= 0:
                return action_result.set_status(phantom.APP_ERROR, "Please provide a non-zero positive integer in 'max results' parameter")
        except:
            return action_result.set_status(phantom.APP_ERROR, "Please provide a non-zero positive integer in 'max results' parameter")

        response = self._paginator('/mgmt/tm/ltm/pool', action_result, limit=max_results)

        if response is None:
            return action_result.get_status()

        for item in response:
            action_result.add_data(item)

        summary = action_result.update_summary({})
        summary['num_pools'] = len(action_result.get_data())

        return action_result.set_status(phantom.APP_SUCCESS)

    def _handle_create_pool(self, param):

        self.save_progress("In action handler for: {0}".format(self.get_action_identifier()))

        action_result = self.add_action_result(ActionResult(dict(param)))

        pool_name = self._handle_py_ver_compat_for_input_str(self._python_version, param['pool_name']).replace('\\', '\\\\').replace('"', '\\"')
        partition_name = self._handle_py_ver_compat_for_input_str(self._python_version, param['partition_name']).replace('\\', '\\\\').replace('"', '\\"')
        pool_description = param.get('pool_description')

        if pool_description:
            # The F5 server requires the below replacement for some special characters as mentioned below.
            # " --> \\\" which gets represented as \\\\\\\" in the Python string
            # \ --> \\\\ which gets represented as \\\\\\\\ in the Python string
            pool_description = self._handle_py_ver_compat_for_input_str(self._python_version, param['pool_description']).replace("\\", "\\\\\\\\").replace(
                '"', '\\\\\\"')
            json_str = '{{"name": "{0}", "partition": "{1}", "description": "{2}"}}'.format(pool_name, partition_name, pool_description)
        else:
            json_str = '{{"name": "{0}", "partition": "{1}"}}'.format(pool_name, partition_name)
        # make rest call
        ret_val, response = self._make_rest_call('/mgmt/tm/ltm/pool', action_result, method="post", data=json_str)
        if (phantom.is_fail(ret_val)):
            return action_result.get_status()
        action_result.add_data(response)

        summary = action_result.update_summary({})
        summary['pool_name'] = pool_name
        summary['partition'] = partition_name
        summary['pool_description'] = pool_description

        return action_result.set_status(phantom.APP_SUCCESS, "Successfully created pool")

    def _handle_list_members(self, param):

        self.save_progress("In action handler for: {0}".format(self.get_action_identifier()))

        action_result = self.add_action_result(ActionResult(dict(param)))

        pool_name = self._handle_py_ver_compat_for_input_str(self._python_version, param['pool_name'])
        partition_name = self._handle_py_ver_compat_for_input_str(self._python_version, param['partition_name'])
        max_results = param.get("max_results")

        try:
            if max_results is not None and int(max_results) <= 0:
                return action_result.set_status(phantom.APP_ERROR, "Please provide a non-zero positive integer in 'max results' parameter")
        except:
            return action_result.set_status(phantom.APP_ERROR, "Please provide a non-zero positive integer in 'max results' parameter")

        response = self._paginator('/mgmt/tm/ltm/pool/~{0}~{1}/members'.format(partition_name, pool_name), action_result, limit=max_results)

        if response is None:
            return action_result.get_status()

        members = []

        for item in response:
            action_result.add_data(item)
            if 'name' in item:
                members.append(item['name'])

        summary = action_result.update_summary({})
        summary['num_members'] = len(action_result.get_data())
        summary['members'] = ', '.join(members)

        return action_result.set_status(phantom.APP_SUCCESS)

    def _handle_get_node_stats(self, param):

        self.save_progress("In action handler for: {0}".format(self.get_action_identifier()))

        action_result = self.add_action_result(ActionResult(dict(param)))

        node_name = self._handle_py_ver_compat_for_input_str(self._python_version, param['node_name'])

        # make rest call
        ret_val, response = self._make_rest_call('/mgmt/tm/ltm/node/{0}/stats'.format(node_name), action_result)

        if phantom.is_fail(ret_val):
            return action_result.get_status()

        try:
            first_entries_key = next(iter(response['entries']))
            stats = response['entries'][first_entries_key]['nestedStats']['entries']
        except Exception as e:
            message = "Unexpected API response. Error: {}".format(e)
            return action_result.set_status(phantom.APP_ERROR, message)

        # replace . with _ for first level keys, since . cannot be a part of key
        # Added list(stats.items()) for Python 2to3 compatibility
        stats = {k.replace('.', '_'): v for k, v in list(stats.items())}

        action_result.add_data(stats)

        summary = action_result.update_summary({})
        summary['num_connections'] = stats['serverside_curConns']['value']

        return action_result.set_status(phantom.APP_SUCCESS, "Successfully retrieved node stats")

    def handle_action(self, param):

        ret_val = phantom.APP_SUCCESS

        # Get the action that we are supposed to execute for this App Run
        action_id = self.get_action_identifier()

        self.debug_print("action_id", self.get_action_identifier())

        if action_id == 'test_connectivity':
            ret_val = self._handle_test_connectivity(param)

        elif action_id == 'create_pool':
            ret_val = self._handle_create_pool(param)

        elif action_id == 'create_node':
            ret_val = self._handle_create_node(param)

        elif action_id == 'delete_node':
            ret_val = self._handle_delete_node(param)

        elif action_id == 'remove_node':
            ret_val = self._handle_remove_node(param)

        elif action_id == 'add_node':
            ret_val = self._handle_add_node(param)

        elif action_id == 'disable_node':
            ret_val = self._handle_disable_node(param)

        elif action_id == 'enable_node':
            ret_val = self._handle_enable_node(param)

        elif action_id == 'describe_node':
            ret_val = self._handle_describe_node(param)

        elif action_id == 'list_nodes':
            ret_val = self._handle_list_nodes(param)

        elif action_id == 'list_pools':
            ret_val = self._handle_list_pools(param)

        elif action_id == 'list_members':
            ret_val = self._handle_list_members(param)

        elif action_id == 'get_node_stats':
            ret_val = self._handle_get_node_stats(param)

        return ret_val

    def initialize(self):

        self._state = self.load_state()

        # get the asset config
        config = self.get_config()

        try:
            self._python_version = int(sys.version_info[0])
        except:
            return self.set_status(phantom.APP_ERROR, "Error occurred while getting the Phantom server's Python major version.")

        self._base_url = self._handle_py_ver_compat_for_input_str(self._python_version, config['base_url'])

        config['username'] = self._handle_py_ver_compat_for_input_str(self._python_version, config['username'])
        config['password'] = self._handle_py_ver_compat_for_input_str(self._python_version, config['password'])

        self._auth = (config['username'], config['password'])

        self.set_validator('ipv6', self._is_ip)

        return phantom.APP_SUCCESS

    def finalize(self):

        # Save the state, this data is saved across actions and app upgrades
        self.save_state(self._state)
        return phantom.APP_SUCCESS


if __name__ == '__main__':

    import pudb
    import argparse

    pudb.set_trace()

    argparser = argparse.ArgumentParser()

    argparser.add_argument('input_test_json', help='Input Test JSON file')
    argparser.add_argument('-u', '--username', help='username', required=False)
    argparser.add_argument('-p', '--password', help='password', required=False)

    args = argparser.parse_args()
    session_id = None

    username = args.username
    password = args.password

    if (username is not None and password is None):

        # User specified a username but not a password, so ask
        import getpass
        password = getpass.getpass("Password: ")

    if (username and password):
        try:
            login_url = F5BigipLtmConnector._get_phantom_base_url() + '/login'

            print("Accessing the Login page")
            r = requests.get(login_url, verify=False)
            csrftoken = r.cookies['csrftoken']

            data = dict()
            data['username'] = username
            data['password'] = password
            data['csrfmiddlewaretoken'] = csrftoken

            headers = dict()
            headers['Cookie'] = 'csrftoken=' + csrftoken
            headers['Referer'] = login_url

            print("Logging into Platform to get the session id")
            r2 = requests.post(login_url, verify=False, data=data, headers=headers)
            session_id = r2.cookies['sessionid']
        except Exception as e:
            print("Unable to get session id from the platform. Error: " + str(e))
            exit(1)

    with open(args.input_test_json) as f:
        in_json = f.read()
        in_json = json.loads(in_json)
        print(json.dumps(in_json, indent=4))

        connector = F5BigipLtmConnector()
        connector.print_progress_message = True

        if (session_id is not None):
            in_json['user_session_token'] = session_id
            connector._set_csrf_info(csrftoken, headers['Referer'])

        ret_val = connector._handle_action(json.dumps(in_json), None)
        print(json.dumps(json.loads(ret_val), indent=4))

    exit(0)
