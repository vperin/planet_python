
"""
Search and download satellite imagery from the Planet platform
"""

from planet import api # v.1.4.4 installing using pypi
from planet.api import filters
import json
import os
import requests
from requests.auth import HTTPBasicAuth
import pandas as pd
import time
import pathlib
from pathlib import Path
from retrying import retry #v.1.3.3

class PlanetClient(object):
    """
    Wrapper of planet API. Planet KEY is necessary. If you do not know yours, please check it here:
    https://developers.planet.com/planetschool/getting-started/
    
    """
    def __init__(self,key='PlanetKey'):
        # add API address for saved searches
        self.url = "https://api.planet.com/data/v1/"
        self.url_quick_search = "{}quick-search".format(self.url)

        # api v2 for bundle downloading and clip tool
        self.url2_base = 'https://api.planet.com/compute/ops'
        self.url2_order = '{}/orders/v2'.format(self.url2_base) # create order url (POST)
        self.url2_download = '{}/download'.format(self.url2_base) # download order url (GET)
        self.headers = {'content-type': 'application/json'}

        # store key as env variable
        os.environ['PL_API_KEY'] = key
        PLANET_API_KEY = os.getenv('PL_API_KEY')

        # session request
        self.ses = requests.Session()
        self.key = PLANET_API_KEY
        if self.key:
            self.ses.auth = (self.key,'')
        else:
            print("ERROR: couldn't find the Planet API key from your system")

class Filter(object):
    """
    Adding multiple filters when performing quick search, saved search and stats. For more info on these topics, please check it here:
    https://developers.planet.com/docs/data/
    
    """
    def __init__(self):
        pass

    def add_geometry_filter(self, geo_json_geometry):
        '''
        Add you geometry as a geojson format to query imagery catalog.
        '''
        return {
                "type": "GeometryFilter",
                "field_name": "geometry",
                "config": geo_json_geometry
                }


    def add_date_filter(self, st='', ed=''):
        '''
        customize the DateRangeFilter. Time boundries are included. 
        '''
        return {
            "type": "DateRangeFilter",
            "field_name": "acquired",
            "config": {"gte": st,
                       "lte": ed}}
    
    def add_cloud_filter(self, cc = 0):
        '''
        Add a cloud filter. Images with cloud-cover below the threshold will be selected.
        '''
        return {
            "type": "RangeFilter",
            "field_name": "cloud_cover",
            "config": {
                "lte": cc
            }
            }
    def add_asset_type(self, asset_one = 'analytic_sr',asset_two = 'analytic'):
        '''
        Add one or two different asset types. The defaul values are: "analytic_sr" and "analytic". 
        '''
        return {
            "type": "AndFilter",
            "config": [
                {"type": "AssetFilter",
                "config": [asset_one]},
                {"type": "AssetFilter",
                    "config": [asset_two]}]}

def get_feature_coord(geojson_path, feature_index):
    '''Function to select one feature of a multi-feature shapefile.
    
    ----------
    Parameters
    ----------
    geojson_path : str
        The path where the geojson file is stores.

    feature_index : int
        The index of the feature in the attribute table; starting from zero. 
    ----------
    Return: 
    ----------
        dict: with feature type (i.e. Polygon) and coordinates. 
    ----------
    Example: 
    ----------
    # Select third bear location from geojson called bear_latlong.geojson.

    geojson_path = "../Desktop/bears_latlong.geojson"
    feature_index = 2

    get_feature_coord(geojson_path,feature_index) 

    Output:

    {'type': 'Polygon',
        'coordinates': [[[682079.523545, 3963563.72741],
        [682080.989577, 3963570.813836],
        [682088.556676, 3963576.634681],
        ...         ...           ...
        [682079.523545, 3963563.72741]]]}

    '''
    import geojson
    with open(geojson_path) as f:
        geojson = geojson.load(f)
    coordinates = geojson['features'][feature_index]['geometry']['coordinates'][0]

    geojson_geometry = {
    "type": "Polygon",
    "coordinates": coordinates
    }

    return geojson_geometry

def get_point_square(lat, lon, size = 0.0004 ):
    '''This function uses the coordinates of a point (i.e. lat and long in decimal degrees) and create a geojson dictionary based on a given size (i.e. distance in decimal degrees). The point is the center of the square.

    ----------
    Parameters
    ----------
    lat: float
        Latitude in decimal degrees. Example: -30.1977440766763.

    lon: float
        Longitude in decimal degrees. Example: 146.610309485323.

    size : float
        The default is to set to size = 0.0004 (~30 meters). 
    ----------
    Return: 
    ----------
        dict: with feature type (i.e. Polygon) and coordinates. 
    ----------
    Example: 
    ----------

    get_point_square(-30.1977440766763,146.610309485323) 

    Output:

    {'type': 'Polygon',
        'coordinates': [[[146.610309485323, -30.1977440766763],
        [146.610709485323, -30.1977440766763],
        [146.610709485323, -30.1981440766763],
        [146.610309485323, -30.1981440766763],
        [146.610309485323, -30.1977440766763]]]}

    '''
    geojson_square = {
    "type": "Polygon",
        "coordinates": [
            [ 
            [lon, lat], #left upper corner 1
            [lon + size, lat], #right upper corner 2
            [lon + size, lat - size], #right lower corner 3
            [lon, lat - size], #left lower corner 4 
            [lon, lat] #left upper corner 1
            ]
        ]
        }
    return geojson_square

def place_order(request,orders_url, auth, headers):
    '''
    Function to place the order on Planet's API. This function uses fallback product bundle; it takes the left most asset type (i.e. analytic_sr, when given multiple asset types), if this is NA then get the analytic

    '''
    #posting the request based on the URL provided
    response = requests.post(orders_url, data=json.dumps(request), auth=auth, headers=headers)
    print(response)
    if not response.ok:
        raise Exception(response.content)
    order_id = response.json()['id']
    print(order_id)
    order_url = orders_url + '/' + order_id
    return order_url

def check_for_success(order_url, auth, num_loops=100):
    '''
    Function to check if clip was already processed or not. 
    '''
    count = 0
    while(count < num_loops):
        count += 1
        r = requests.get(order_url, auth=auth)
        response = r.json()
        state = response['state']
        print(state)
        success_states = ['success', 'partial']
        if state == 'failed':
            raise Exception(response)
        elif state in success_states:
            break
        # sleep while the API process
        time.sleep(30)

# Download imagery with xml and metadata
@retry(
wait_exponential_multiplier=1000,
wait_exponential_max=10000)
def download_order(order_url, auth, save_dir,feature_name, overwrite=False):
    r = requests.get(order_url, auth=auth)
    print('stuck in download_order')
    response = r.json()
    
    # parse out useful links
    results = response['_links']['results']
    results_urls = [r['location'] for r in results]
    results_names = [r['name'] for r in results]

    #create directory and separate images by feature_name
    results_paths = [pathlib.Path(os.path.join(save_dir + "/" + feature_name + "/", os.path.basename(n))) for n in results_names]
    print('{} items to download'.format(len(results_urls)))
    
    for url, name, path in zip(results_urls, results_names, results_paths):
        if overwrite or not path.exists():
            print('downloading {} to {}'.format(name, path))
            r = requests.get(url, allow_redirects=True)
            path.parent.mkdir(parents=True, exist_ok=True)
            open(path, 'wb').write(r.content)
        else:
            print('{} already exists, skipping {}'.format(path, name))

# Define cols df to save files; this is product dependent.
cols = {'PSScene4Band':['id','acquired','cloud_cover','origin_x','origin_y',"view_angle","sun_azimuth","sun_elevation","anomalous_pixels"],
        'PSOrthoTile':['id','acquired','cloud_cover','origin_x','origin_y',"view_angle","sun_azimuth","sun_elevation","anomalous_pixels","usable_data"],
        'REOrthoTile':['id','acquired','cloud_cover','origin_x','origin_y',"view_angle","sun_azimuth","sun_elevation","anomalous_pixels","usable_data"]}

def planet_search(planet_key,item_type, st, ed, geojson, save_dir,search_name = 'reg_search',cc = 0):
    '''Function to search Planet's imagery. This function uses the coordinates of a geojson file as the AOI to query for available images.

    ----------
    Parameters
    ----------
    planet_key: str
        Planet API key available on their website. The API key looks like this: "f4514fce28094f3b9asd9eff96399c9b01b".

        For more information: https://developers.planet.com/planetschool/getting-started/

    item_type: str
        Three options are available: "PSScene4Band", "PSOrthoTile" and "REOrthoTile" 

    st: str
        Initial date to seach query the image catalog. Example: "2019-07-01T16:00:00.000Z".

    ed: str
        End date to seach query the image catalog. Example: "2019-08-30T23:59:59.999Z".

    geojson: dict
        Geojson dictionary. Example from get_feature_coord:

            {'type': 'Polygon',
                'coordinates': [[[682079.523545, 3963563.72741],
                [682080.989577, 3963570.813836],
                [682088.556676, 3963576.634681],
                ...         ...           ...
                [682079.523545, 3963563.72741]]]}

    save_dir: str
        Directory to save csv file output.

    search_name: str - optional
        Search identification name. The search_name appears on Planet's API for future reference.

    cc: float (between 0 and 1) - optional
        Cloud cover filter when querying the images. The default value is set cloud_cover = 0.

    ----------
    Return: 
    ----------
        csv: with the images id and other properties (e.g. cloud cover, view angle, usable data, etc.)
    ----------
    Example: 
    ----------
    planet_search(planet_key='fce28094f3asdb99eff96399c9b01b',
        item_type = PSOrthoTile,
        st = "2016-01-01T16:00:00.000Z", ed = "2019-01-01T16:00:00.000Z",
        geojson = get_feature_coord(geojson,2)
        save_dir = "output/csvs/",
        search_name= "test search",
        cc = 0.25)

    '''
    def handle_page(page, item_type, empty_list):
        '''
        Function that we pass the first page of the search and the empty list

        '''
        for item in page["features"]:
            #save metadata that we want!
            #printing some other different options
            #list of properties that we want from each image; this will depend on the product, which is why we need to create a flag here.
            if item_type == 'PSScene4Band':
                lst = \
                [item["id"],
                item['properties']["acquired"],
                item['properties']['cloud_cover'],
                item['properties']['origin_x'],
                item['properties']['origin_y'],
                item['properties']['view_angle'],
                item['properties']['sun_azimuth'],
                item['properties']['sun_elevation'],
                item['properties']['anomalous_pixels']]
            elif item_type == 'PSOrthoTile':
                lst = \
                [item["id"],
                item['properties']["acquired"],
                item['properties']['cloud_cover'],
                item['properties']['origin_x'],
                item['properties']['origin_y'],
                item['properties']['view_angle'],
                item['properties']['sun_azimuth'],
                item['properties']['sun_elevation'],
                item['properties']['anomalous_pixels'],
                item['properties']["usable_data"]]
            elif item_type == 'REOrthoTile':
                lst = \
                [item["id"],
                item['properties']["acquired"],
                item['properties']['cloud_cover'],
                item['properties']['origin_x'],
                item['properties']['origin_y'],
                item['properties']['view_angle'],
                item['properties']['sun_azimuth'],
                item['properties']['sun_elevation'],
                item['properties']['anomalous_pixels'],
                item['properties']["usable_data"]]
            else:
                print('Please check the name of your item_type, it should be: PSScene4Band or PSOrthoTile')
            empty_list.append(lst)
            print (item['properties']['acquired']) #printing when the image was acquired

    # once we enter the first page, we need to go and move to next ones.
    def fetch_page(session, search_url):
        page = session.get(search_url).json()
        res_code = session.get(search_url).status_code

        #print('status_code: %s'%res_code) 
        while res_code == 429: # avoid spamming requests
            print('rate of requests too high! sleep 1s...')
            time.sleep(1)
            page = session.get(search_url).json()
            res_code = session.get(search_url).status_code

        handle_page(page,item_type, store_list) #3rd argumente item_type
        
        next_url = page["_links"].get("_next")
        
        if next_url:
            fetch_page(session, next_url)

    # Define Filters and append to a list to create combined filters
    Filters = []

    # add filter to Filters()
    filter_geom = Filter().add_geometry_filter(geo_json_geometry = geojson)
    Filters.append(filter_geom)
    filter_date = Filter().add_date_filter(st = st, ed =ed)
    Filters.append(filter_date)
    filter_cloud = Filter().add_cloud_filter(cc = cc) #only get images which have <50% cloud coverage
    Filters.append(filter_cloud)
    filter_asset = Filter().add_asset_type(asset_one='analytic_sr',asset_two='analytic')
    Filters.append(filter_asset)

    # combine our geo, date, cloud filters
    combined_filter = {"type": "AndFilter","config": Filters}
    # prepare search request
    search_request = {"item_types": [item_type],"filter": combined_filter}

    # using class PlanetClient to post
    client = PlanetClient(key = planet_key)
    res = client.ses.post(client.url_quick_search, auth=client.ses.auth, json=search_request)
    geojson = res.json()

    # get first link of the search to paginate
    link_first_page = geojson['_links']['_first']
    # empty list to store search!
    store_list = [] 
    # parse info from different pages
    fetch_page(client.ses, link_first_page)
    # add data to pd.dataFrame
    df = pd.DataFrame(store_list, columns=cols[item_type])
    # name to save df
    name = item_type + '_' + search_name + '.csv'

    # handle directory problem
    up_dir = save_dir.replace('/',"")
    directory = os.getcwd() + '\\' + up_dir 

    if os.path.exists(directory) == False:
        os.makedirs(directory)
        df.to_csv(directory + '/' + name)
        print('DataFrame was saved at: {0}'.format(directory))

    else:
        df.to_csv(directory + '/' + name)
        print('DataFrame was saved at: {0}'.format(directory))

def planet_download_clip(planet_key, geojson, feature_name, items_id, item_type, save_dir):
    '''Function to download clipped imagery from Planet's catalog.

    ----------
    Parameters
    ----------

    planet_key: str
        Planet API key available on their website. The API key looks like this: "f4514fce28094f3b9asd9eff96399c9b01b".

        For more information: https://developers.planet.com/planetschool/getting-started/

    geojson: dict
        Geojson dictionary. Example from get_feature_coord:

            {'type': 'Polygon',
                'coordinates': [[[682079.523545, 3963563.72741],
                [682080.989577, 3963570.813836],
                [682088.556676, 3963576.634681],
                ...         ...           ...
                [682079.523545, 3963563.72741]]]}
    
    feature_name: str
        A string that identifies the feature (e.g. useful when a multi-feature shapefile is used or to simply identify a point.). Example: 'Reservoir_775'

    items_id: list
        A flat list with the images ids. This list is obtained after running the function planet_search.

    item_type: str
        Three options are available: "PSScene4Band", "PSOrthoTile" and "REOrthoTile" 

    save_dir: str
        Directory to save csv file output.

    ----------
    Return: 
    ----------

        Clipped imagery and metadata (.tif, xml, JSON)

    ----------
    Example: 
    ----------

    planet_download_clip(
        planet_key = planet_key,
        geojson = geojson,
        feature_name = folder_name,
        items_id = ortho_ids['id'].to_list(),
        item_type = item_type,
        save_dir = save_dir)

    '''
    
    # Define product specifications! This is an important step.
    same_src_products = [{"item_ids": items_id,
                          "item_type": item_type,
                          "product_bundle": "analytic_sr,analytic"}]

    # get geojson coordinates geometry
    clip_aoi = geojson
    # define the clip tool to use in the API!
    clip = {"clip": {"aoi": clip_aoi}}
    # create an order request with the clipping tool
    request_clip = {"name": "just clip","products": same_src_products,"tools": [clip]}
    # using class PlanetClient
    client = PlanetClient(key = planet_key)

    try:
        # Run clip the place_order and store url
        clip_order_url = place_order(request = request_clip, orders_url = client.url2_order,
                                     auth = client.ses.auth, headers = client.headers)

        #check the status of the order
        check_for_success(clip_order_url, auth = client.ses.auth)

        #download the clip once we reach success
        downloaded_clip_files = download_order(order_url = clip_order_url, auth = client.ses.auth ,save_dir = save_dir, feature_name = feature_name)

    except Exception as error:
        error_string = str(error)
        print('An error occured for {0}'.format(feature_name))
        print(error_string)

        #save the error message to identify images with problems
        Path(os.path.join(save_dir,'errors')).mkdir(parents = True, exist_ok=True)
        text_file = open(save_dir + '/errors/' + feature_name + '_error_message.txt', "w")
        text_file.write(error_string)
        text_file.close()

        pass # move on to the next point