import argparse
import json
import logging
import os
import random
import time
import urllib
import urllib2
import xml.etree.cElementTree as ET

import requests
import urllib3
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from requests.packages.urllib3.exceptions import InsecureRequestWarning

requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

JSON_END = "};"

JSON_START = "window.__listing_ItemsStoreState = "


def setup_logger():
    logger = logging.getLogger('extractor')
    logging.basicConfig(level=logging.DEBUG)
    logging.getLogger("urllib3.connectionpool").setLevel(logging.ERROR)
    return logger


def setup_arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--allegro", nargs='+')
    parser.add_argument("--olx", nargs='+')
    parser.add_argument("--banned", nargs='+')
    parser.add_argument("--banned_file")
    parser.add_argument("--google_key")
    return parser.parse_args()


def fetch_and_parse_page(url):
    html_doc = requests.get(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/'}).content
    # html_doc = urllib2.urlopen(url).read()
    return BeautifulSoup(html_doc, 'html.parser')


def is_banned(name):
    if banned:
        for ban in banned:
            if ban in name.lower():
                return True
    return False


def extended_data(parent, key, value):
    data = ET.SubElement(parent, "Data", name=key)
    ET.SubElement(data, "value").text = value


def to_allegro_category(path):
    category_key = path[-1]
    if not category_key in allegro_category_cache:
        page = fetch_and_parse_page('https://allegro.pl/kategoria/santa-fe-i-2000-2006-' + category_key)
        allegro_category_cache[category_key] = page.title.text.replace(' - Allegro.pl', '')
    return allegro_category_cache[category_key]


def to_geocode(loc):
    geocode_result = locator.decode_location(loc)
    # adding some randomness to see more than one point in city if there are more than one offer in a single city
    lng_shift = random.uniform(-0.009, 0.009)
    lat_shift = random.uniform(-0.009, 0.009)
    return str(geocode_result['lng'] + lng_shift) + ',' + str(geocode_result['lat'] + lat_shift)


def to_uber_category(name):
    name_lower = name.lower()
    if 'explorer' in name_lower:
        return 'explorer'
    if 'pajer' in name_lower:
        return 'pajero'
    if 'cheroke' in name_lower:
        return 'cherokee'
    if 'fronter' in name_lower:
        return 'frontera'
    if 'range' in name_lower:
        return 'range'
    return 'inny'


def allegro_query(base_url):
    p = 1
    while True:
        logger.debug("p: %s", str(p))
        page = fetch_and_parse_page(base_url + "&p=" + str(p))
        for article in page.find_all('script'):
            text = article.text
            if JSON_START not in text:
                continue
            start = text.find(JSON_START) + len(JSON_START)
            end = text.find(JSON_END, start) + 1
            jsonText = text[start:end]
            jsonParsed = json.loads(jsonText)
            for group in jsonParsed["itemsGroups"]:
                if group['sponsored']:
                    continue
                for item in group['items']:
                    name = item['title']['text']
                    id_ = item['id']
                    if id_ in processed_ids:
                        logger.debug("Skip already processed. %s", name)
                        continue
                    processed_ids.add(id_)
                    if 'thumbnail' not in item:
                        logger.debug("Skip article without picture. %s", name)
                        continue
                    if is_banned(name):
                        logger.debug("Skip banned article. %s", name)
                        continue
                    category = to_allegro_category(item['categoryPath'])
                    if is_banned(category):
                        logger.debug("Skip banned category. %s", category)
                        continue
                    img = item['thumbnail']
                    item_page_link = item['url']
                    location = item['location']
                    # logger.info("Loca: %s", geocode_result)
                    placemark = ET.SubElement(doc, "Placemark")
                    ET.SubElement(placemark, "name").text = name
                    ET.SubElement(placemark, "description").text = '<a href="' + item_page_link + '"><img src="' + img + '"/></a>'
                    ed = ET.SubElement(placemark, "ExtendedData")
                    extended_data(ed, "source", "Allegro")
                    extended_data(ed, "link", item_page_link)
                    extended_data(ed, "location", location)
                    extended_data(ed, "category", category)
                    extended_data(ed, "uber_category", to_uber_category(name))
                    extended_data(ed, "price", item['price']['normal']['amount'])
                    for attr in item['attributes']:
                        extended_data(ed, attr['name'], attr['value'])
                    point = ET.SubElement(placemark, "Point")
                    ET.SubElement(point, "coordinates").text = to_geocode(location)
                    logger.debug("Title: " + name)
        p += 1
        if p > int(page.find("li", attrs={"class": "quantity"}).text):
            break


def olx_query(base_url):
    p = 1
    while True:
        logger.debug("page: %s", str(p))
        page = fetch_and_parse_page(base_url + "&page=" + str(p))
        for offer in page.find_all('td', attrs={"class": "offer"}):
            if not offer.find('table'):
                logger.debug("Offer without table?. %s", offer)
                continue
            the_a = offer.a
            id_ = offer.table['data-id']
            if id_ in processed_ids:
                logger.debug("Skip already processed. %s", the_a['href'])
                continue
            processed_ids.add(id_)
            if not the_a.find('img'):
                logger.debug("Skip article without picture. %s", the_a['href'])
                continue
            name = the_a.img['alt']
            if is_banned(name):
                logger.debug("Skip banned article. %s", name)
                continue
            img = the_a.img['src']
            item_page_link = the_a['href']
            location = ''
            category = ''
            for small in offer.find_all('small'):
                if small.find('span'):
                    location = small.span.text.strip()
                else:
                    category = small.text.strip().replace('Samochody osobowe', '')[3:]
            if is_banned(category):
                logger.debug("Skip banned category. %s", category)
                continue
            placemark = ET.SubElement(doc, "Placemark")
            ET.SubElement(placemark, "name").text = name
            ET.SubElement(placemark, "description").text = '<a href="' + item_page_link + '"><img src="' + img + '"/></a>'
            ed = ET.SubElement(placemark, "ExtendedData")
            extended_data(ed, "source", "Olx")
            extended_data(ed, "link", item_page_link)
            extended_data(ed, "location", location)
            extended_data(ed, "category", category)
            extended_data(ed, "uber_category", to_uber_category(name))
            extended_data(ed, "price", offer.find('p', attrs={'class': 'price'}).strong.text[:-3].replace(' ', ''))
            point = ET.SubElement(placemark, "Point")
            ET.SubElement(point, "coordinates").text = to_geocode(location)
            logger.debug("Title: " + name)
        p += 1
        pager = page.find("form", attrs={"id": "pagerGoToPage"})
        if not pager:
            break
        if p > int(pager.find('input', attrs={'type': 'submit'})['class'][1][:-1]):
            break


class GeoLocatorWithCache:
    filepath = 'location.cache'

    def __init__(self, key):
        if os.path.isfile(GeoLocatorWithCache.filepath):
            with open('location.cache', 'a+b') as cache_file:
                self.known = json.load(cache_file, encoding="UTF-8")
        else:
            self.known = {}
        self.key = key

    def _find_location(self, location):
        encoded = urllib.quote(location.encode('utf-8'))
        return json.loads(
                urllib2.urlopen("https://maps.googleapis.com/maps/api/geocode/json?address=" + encoded + "&region=pl&key=" + self.key).read())[
            'results'][0]['geometry']['location']

    def decode_location(self, location):
        result = self.known.get(location)
        if result:
            return result
        found = self._find_location(location)
        self.store_in_cache(location, found)
        return found

    def store_in_cache(self, location, geometry_location):
        self.known[location] = geometry_location
        with open(GeoLocatorWithCache.filepath, 'w+b') as cache_file:
            json.dump(self.known, cache_file)


logger = setup_logger()
args = setup_arguments()

timestr = time.strftime("%Y%m%d-%H%M%S")
if args.banned:
    banned = args.banned
else:
    if args.banned_file:
        with open(args.banned_file, 'r') as bf:
            banned = bf.readlines()
            banned = map(lambda s: s.strip().lower(), banned)
    else:
        banned = []

allegro_category_cache = {}

root = ET.Element("kml")
doc = ET.SubElement(root, "Document")
processed_ids = set()
locator = GeoLocatorWithCache(args.google_key)

if args.allegro:
    logger.info("Allegro searches")
    for a in args.allegro:
        logger.debug("q: %s", a)
        allegro_query(a)

if args.olx:
    logger.info("Olx searches")
    for a in args.olx:
        logger.debug("q: %s", a)
        olx_query(a)

tree = ET.ElementTree(root)
tree.write("offers_" + timestr + ".kml")
