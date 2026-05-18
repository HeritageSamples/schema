#!/usr/bin/env python3
# Vendored from kikirpa/cordra-config/scripts/lib/libcordra.py (minimal changes).

'''
This is a python module that provides a simple interface to the Cordra API.
It contains a single class, Cordra, which provides methods for accessing
and manipulating Cordra objects. The class contains the following methods:

Core CRUD Operations:
    - get_by_handle: retrieves a Cordra object by its handle/PID
    - query: returns a list of Cordra objects that match a specific query
    - query_count: returns the count of objects matching a query
    - create: creates a new Cordra object
    - update: updates an existing Cordra object
    - delete: deletes an existing Cordra object

Batch Operations:
    - batch_upload: uploads a batch of Cordra objects

Payload Operations:
    - download_payload: downloads a payload from a Cordra object
    - create_object_with_payloads: creates a new Cordra object with a payload
    - update_object_with_payloads: uploads a list of payloads to a Cordra object

Version Management:
    - get_versions: returns a list of versions of a specific Cordra object
    - create_version: creates a new version of a Cordra object

Type Methods:
    - call_type_method: calls a type method on a Cordra object

System Operations:
    - get_token: gets an authentication token from Cordra
    - update_design: updates the design object and its custom authentication payload
    - reindex: reindexes objects in Cordra (specific objects, query results, or all objects)

Utility Functions:
    - generate_hdl_suffix: creates a random string for handle ID generation

'''

import sys
import random
import string
import json
import shutil

import requests


# disable SSLerror for self-signed certificates
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class Cordra:
    def __init__(self, url, username, password, verify=False):
        self.url = url
        self.username = username
        self.password = password
        self.verify = verify

        # if username and password are provided, get a token
        if self.username and self.password:
            self.token = self.get_token()
            self.headers = {"Authorization": f"Bearer {self.token}"}
        else:
            self.token = None
            self.headers = {}


    '''
    get_token: gets a token from Cordra
    '''
    def get_token(self):
        response = requests.post(
            '{}/auth/token'.format(self.url), 
            json={'username': self.username, 'password': self.password},
            verify=self.verify)
        if response.status_code != 200:
            print(response.text, flush=True)
            print('!! Error: Unable to get token from Cordra !!', flush=True)
            print(f' - response from Cordra: {response.text}', flush=True)
            sys.exit(1)
        return response.json()['access_token']


    '''
    get_by_handle: gets a Cordra object by handle
    '''
    def get_by_handle(self, pid, full=False, json_pointer=None, filter=None, payload=None):
        # make a parameter string
        parameters = []
        if full:
            parameters.append('full')
        if json_pointer:
            parameters.append(f'jsonPointer={json_pointer}')
        if filter:
            parameters.append(f'filter={filter}')
        if payload:
            parameters.append(f'payload={payload}')
        # join the parameters with &
        parameter_string = "&".join(parameters)
        if parameter_string:
            parameter_string = "?" + parameter_string
        # make the request
        response = requests.get(
            f'{self.url}/objects/{pid}{parameter_string}', 
            headers=self.headers, 
            verify=self.verify)
        if response.status_code != 200:
            print('!! Error: Unable to retrieve object from Cordra !!', flush=True)
            print(f' - response from Cordra: {response.text}', flush=True)
            sys.exit(1)
        if not payload:
            return response.json()
        else: # we should get a payload (no json)
            return response.content
        

    '''
    query: returns a list of Cordra objects that match a specific query
        filter: a list of jsonpointers to limit the fields returned
    '''
    def query(self, query, page_num=0, page_size=-1, filter=None, full=False, ids=False, include_versions=False):
        post_data = {
            'query': query,
            'pageNum': page_num,
            'pageSize': page_size
        }
        # if filter is present and a list, add it to the post data
        if filter and isinstance(filter, list):
            post_data['filter'] = filter
        if include_versions:
            post_data['includeVersions'] = True
        # full and ids are mutually exclusive
        if full:
            post_data['full'] = True
        elif ids:
            post_data['ids'] = True
        response = requests.post(
            f'{self.url}/search', 
            json=post_data, 
            headers=self.headers, 
            verify=self.verify)
        if response.status_code != 200:
            print('!! Error: Unable to retrieve objects from Cordra !!', flush=True)
            print(f' - response from Cordra: {response.text}', flush=True)
            sys.exit(1)
        return response.json()['results']


    '''
    query_count: returns the number of objects that match a specific query
    '''
    def query_count(self, query, include_versions=False):
        post_data = {
            'query': query,
            'pageNum': 0,
            'pageSize': 1,
            'filter': ['/id']
        }
        if include_versions:
            post_data['includeVersions'] = True
        response = requests.post(
            f'{self.url}/search', 
            json=post_data, 
            headers=self.headers, 
            verify=self.verify)
        if response.status_code != 200:
            print('!! Error: Unable to retrieve object count from Cordra !!', flush=True)
            print(f' - response from Cordra: {response.text}', flush=True)
            sys.exit(1)
        return response.json()['size']


    '''
    create: creates a new Cordra object
    '''
    def create(self, obj, type, pid=None, full=False):
        pid = f'&handle={pid}' if pid else ''
        full = '&full' if full else ''
        response = requests.post(
            f'{self.url}/objects/?type={type}{pid}{full}', 
            json=obj, 
            headers=self.headers, 
            verify=self.verify)
        if response.status_code != 200:
            print('!! Error: Unable to create object in Cordra !!', flush=True)
            print(f' - response from Cordra: {response.text}', flush=True)
            sys.exit(1)
        return response.json()


    '''
    update: updates an existing Cordra object
    '''
    def update(self, pid, obj, full=False):
        full = '?full' if full else ''
        response = requests.put(
            f'{self.url}/objects/{pid}{full}', 
            json=obj, 
            headers=self.headers, 
            verify=self.verify)
        if response.status_code != 200:
            print('!! Error: Unable to update object in Cordra !!', flush=True)
            print(f' - response from Cordra: {response.text}', flush=True)
            sys.exit(1)
        return response.json()


    '''
    delete: deletes an existing Cordra object
    '''
    def delete(self, pid):
        response = requests.delete(
            f'{self.url}/objects/{pid}', 
            headers=self.headers, 
            verify=self.verify)
        if response.status_code != 200:
            print('!! Error: Unable to delete object in Cordra !!', flush=True)
            print(f' - response from Cordra: {response.text}', flush=True)
            sys.exit(1)
        return response.json()


    '''
    batch_upload: uploads a batch of Cordra objects
    '''
    def batch_upload(self, objects):
        response = requests.post(
            f'{self.url}/batchUpload', 
            json=objects, 
            headers=self.headers, 
            verify=self.verify)
        if response.status_code != 200:
            print('!! Error: Unable to upload batch of objects to Cordra !!', flush=True)
            print(f' - response from Cordra: {response.text}', flush=True)
            sys.exit(1)
        return response.json()
    

    '''
    create_object_with_payloads: creates a new Cordra object with a payload
    payloads is a dictionary with 
     - keys: "name"
     - values: a tuple of (filename, file handle)
    '''
    def create_object_with_payloads(self, do, type, payloads, full=False):
        full = '&full' if full else ''
        # create a multipart/form-data request
        files = {
            "content": (None, json.dumps(do)),
        }
        for name, value in payloads.items():
            files[name] = value
        # make the request
        response = requests.post(
            f'{self.url}/objects/?type={type}{full}', 
            headers=self.headers, 
            files=files,
            verify=self.verify)
        if response.status_code != 200:
            print('!! Error: Unable to create object with payloads in Cordra !!', flush=True)
            print(f' - response from Cordra: {response.text}', flush=True)
            sys.exit(1)
        return response.json()
    

    '''
    update_object_with_payloads: uploads a dictionary of payloads to a Cordra object
    payloads is a dictionary with 
     - keys: "name"
     - values: a tuple of (filename, file handle)
    '''
    def update_object_with_payloads(self, pid, payloads, do=None, full=False):
        full = '?full' if full else ''
        # create a multipart/form-data request
        files = {}
        if not do: # NOTE: the api returns an error if the content is not provided
            do = self.get_by_handle(pid, full=True)
            do = do['content']
        files["content"] = (None, json.dumps(do))
        # add the payloads to the files
        for name, value in payloads.items():
            files[name] = value
        # make the request
        response = requests.put(
            f'{self.url}/objects/{pid}{full}', 
            headers=self.headers, 
            files=files,
            verify=self.verify)
        if response.status_code != 200:
            print('!! Error: Unable to upload payloads to Cordra !!', flush=True)
            print(f' - response from Cordra: {response.text}', flush=True)
            sys.exit(1)
        return response.json()


    '''
    download_payload: downloads a payload from a Cordra object
    '''
    def download_payload(self, pid, payload, path):
    
        with requests.get(
            f'{self.url}/objects/{pid}?payload={payload}', 
            stream=True,
            headers=self.headers,
            verify=self.verify
        ) as r:
            with open(path, 'wb') as f:
                shutil.copyfileobj(r.raw, f)
        

    '''
    get_versions: returns a list of versions of a specific Cordra object
    '''
    def get_versions(self, pid):
        # get the versions of the object
        response = requests.get(
            f'{self.url}/versions/?objectId={pid}', 
            headers=self.headers, 
            verify=self.verify)
        if response.status_code != 200:
            print('!! Error: Unable to retrieve versions from Cordra !!', flush=True)
            print(f' - response from Cordra: {response.text}', flush=True)
            sys.exit(1)
        version_list = response.json()
        # create simple list of versions, excluding the current version
        versions = []
        for item in version_list:
            if item['id'] != pid:
                versions.append(item['id'])
        return versions
    

    '''
    create_version: creates a new version of a Cordra object
    '''
    def create_version(self, pid, version_pid=None):
        version_pid = f'&versionId={version_pid}' if version_pid else ''
        # create the version
        response = requests.post(
            f'{self.url}/versions/?objectId={pid}{version_pid}', 
            headers=self.headers, 
            verify=self.verify)
        if response.status_code != 200:
            print('!! Error: Unable to create version in Cordra !!', flush=True)
            print(f' - response from Cordra: {response.text}', flush=True)
            sys.exit(1)
        return response.json()
    

    '''
    update_design: update the design object and its custom authentication payload
    '''
    def update_design(self, design, payload=None):
        # when posting/updating an object including payloads, the request
        # must be a multipart/form-data request!!!
        # https://stackoverflow.com/questions/12385179/how-to-send-a-multipart-form-data-with-requests-in-python
        url = self.url + "/objects/design"
        if payload is not None:
            files = {
                "content": (None, design),
                "customAuthentication.html": (      # file=
                    "customAuthentication.html",    # filename=
                    payload, 
                    "text/html"
                )
            }
            response = requests.put(
                url, 
                headers=self.headers, 
                files=files,
                verify=self.verify)
        else:
            response = requests.put(
                url,
                headers=self.headers, 
                json=json.loads(design),
                verify=self.verify)
        if response.status_code != 200:
            print('!! Error: Unable to update design object in Cordra !!', flush=True)
            print('\n -- DEBUG --', flush=True)
            print('Request:', flush=True)
            print(response.request.body.decode("utf-8"), flush=True)
            print('Request Headers:', flush=True)
            print(response.request.headers, flush=True)
            print('Response Headers:', flush=True)  
            print(response.headers, flush=True)
            print('Response status code:', flush=True)
            print(response.status_code, flush=True)
            print('Response:', flush=True)
            print(response.text, flush=True)
            sys.exit(1)

        return True
    

    '''
    reindex: reindex a list of objects or all objects in a cordra instance
    '''
    def reindex(self, objects=None, query=None, all=False, lock_objects=True, timeout=30):
        parameters = {}
        body = None
        if all:
            parameters['all'] = True
        elif query:
            parameters['query'] = query
        elif objects and isinstance(objects, list):
            body = objects
        else:
            return False
        
        if lock_objects:
            parameters['lockObjects'] = True
        
        parameter_string = ""
        if len(parameters) > 0:
            parameter_string += "?" + "&".join([f"{key}={value}" for key, value in parameters.items()])

        print(f'{self.url}/reindexBatch{parameter_string}', flush=True)
        try:
            if body is not None:
                response = requests.post(
                    f'{self.url}/reindexBatch{parameter_string}', 
                    json=body,
                    headers=self.headers,
                    verify=self.verify,
                    timeout=timeout)
            else:
                response = requests.post(
                    f'{self.url}/reindexBatch{parameter_string}',
                    headers=self.headers,
                    verify=self.verify,
                    timeout=timeout)
            if response.status_code != 200:
                print('!! Error: Unable to reindex objects in Cordra !!', flush=True)
                print(f' - response from Cordra: {response.text}', flush=True)
                sys.exit(1)
        except requests.exceptions.Timeout:
            print("Timeout... (this is usually a good sign and means that the server is busy reindexing)", flush=True)
            return None
        return None


    '''
    call_type_method: calls a type method on a Cordra object
    '''
    def call_type_method(self, pid, method, input=None):
        # build the url
        url = f'{self.url}/cordra/call?objectId={pid}&method={method}'
        # make the request
        response = requests.post(
            url,
            headers=self.headers,
            json=input,
            verify=self.verify)
        if response.status_code != 200:
            print('!! Error: Unable to call type method on Cordra object !!', flush=True)
            print(f' - response from Cordra: {response.text}', flush=True)
            sys.exit(1)
        return response.json()


'''
generate_hdl_suffix: create a random string for the handle id
'''
def generate_hdl_suffix(
        format="alphanumeric", 
        upper=False,
        length=8, 
        in_groups_of=4,
        group_separator="."):

    # define the format characters
    if format == "hexadecimal":
        format_characters = string.hexdigits
    else:
        format_characters = string.ascii_lowercase + string.digits

    # create a list of random characters in groups
    groups = []
    number_of_groups = length // in_groups_of
    for i in range(0, number_of_groups):
        groups.append("".join(random.choices(format_characters, k=in_groups_of)))
    # add the last group
    if length % in_groups_of > 0:
        groups.append("".join(random.choices(format_characters, k=length % in_groups_of)))

    # build string
    suffix = group_separator.join(groups)
    if upper:
        suffix = suffix.upper()
    
    return suffix    


if __name__ == '__main__':
    print('This is a module, not a script!')