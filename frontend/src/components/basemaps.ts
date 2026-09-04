/** The map styles the fleet map offers.
 *
 * Their own module rather than sitting beside the component: a file that
 * exports both a component and constants breaks React Fast Refresh, and
 * this list is data the page needs too - the picker lives in the
 * monitoring toolbar, not inside the map.
 */
// Required by the ODbL: OpenStreetMap data has to be credited wherever it
// is shown. Leaflet's own "Leaflet |" prefix is courtesy rather than law,
// and is switched off on the control below.
const OSM_CREDIT =
  '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a>'

// The basemaps on offer, all of them keyless.
//
// The set is the one fleet products actually ship. Motive offers Street,
// Satellite and Traffic; Samsara offers street, terrain and satellite. The
// common, expected pair is Street and Satellite - Terrain is a hiking map
// and was the odd one out here. Traffic needs a paid live feed, so it is
// not on offer rather than faked.
//
// Dark is not a separate tile set: OSM publishes one style and it is a
// light one, so the dark option inverts it in CSS and rotates the hue back.
// That works on a road map with few saturated colours - it is why terrain,
// which is nothing but saturated colour, looked wrong under it.
//
// Satellite is Sentinel-2 cloudless from EOX, which covers the whole world
// and needs no key.
//
// The licence is the reason it is this one and not a sharper alternative:
//
//   * EOX publish several years of this layer. Everything from 2018 on is
//     CC BY-NC-SA - non-commercial. Unector is a paid product, so
//     those are not available to it however good they look. The 2016 layer
//     is plain CC BY 4.0, which is.
//   * Esri's World Imagery is sharper and still answers on its legacy
//     endpoint, but their current terms point at a basemap service that
//     wants a token, and CARTO now wants one too.
//   * USGS imagery is public domain and sharper again, but stops at the US
//     border, and this map should work wherever a truck is.
//
// So: worldwide, keyless, and licensed for commercial use, at the cost of
// some resolution. The attribution below is a condition of that licence.
export type BasemapId = 'street' | 'satellite' | 'dark'

export interface Basemap {
  label: string
  url: string
  attribution: string
  maxZoom: number
  /** Inverted in CSS to make a dark map out of a light tile set. Only ever
   *  true for the keyless fallback - Mapbox ships a real dark style. */
  invert?: boolean
  /** Mapbox serves 512px tiles; Leaflet assumes 256 and needs telling. */
  tileSize?: number
  zoomOffset?: number
  /** Mapbox's terms require their wordmark on the map, not just text. */
  logo?: 'mapbox'
}

const KEYLESS: Record<BasemapId, Basemap> = {
  street: {
    label: 'Street',
    url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
    attribution: OSM_CREDIT,
    maxZoom: 19,
  },
  satellite: {
    label: 'Satellite',
    url: 'https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless_3857/default/g/{z}/{y}/{x}.jpg',
    attribution:
      'Sentinel-2 cloudless by <a href="https://eox.at" target="_blank" rel="noreferrer">EOX IT Services GmbH</a>' +
      ' (contains modified Copernicus Sentinel data 2016)',
    maxZoom: 15,
  },
  dark: {
    label: 'Dark',
    url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
    attribution: OSM_CREDIT,
    maxZoom: 19,
    invert: true,
  },
}

// ---------------------------------------------------------------------
// Mapbox, when a token is configured.
//
// Sharper than the keyless set and it has a real dark style rather than an
// inverted light one, so `invert` is off here. The token is public by
// design - Mapbox issues it to be embedded - and is restricted by URL in
// their dashboard rather than kept secret. See MAPBOX_TOKEN in config.py.
//
// Their attribution terms want three links and the Mapbox wordmark. The
// links go in the attribution string; the wordmark is drawn by the map
// component when `logo` is set. Neither is optional on these styles.
// ---------------------------------------------------------------------
const MAPBOX_CREDIT =
  '&copy; <a href="https://www.mapbox.com/about/maps/" target="_blank" rel="noreferrer">Mapbox</a> ' +
  OSM_CREDIT +
  ' <a href="https://www.mapbox.com/map-feedback/" target="_blank" rel="noreferrer">Improve this map</a>'

function mapboxStyle(label: string, style: string, token: string): Basemap {
  return {
    label,
    url:
      `https://api.mapbox.com/styles/v1/mapbox/${style}/tiles/512/{z}/{x}/{y}@2x` +
      `?access_token=${encodeURIComponent(token)}`,
    attribution: MAPBOX_CREDIT,
    maxZoom: 20,
    tileSize: 512,
    zoomOffset: -1,
    logo: 'mapbox',
  }
}

/** The basemaps to offer. Mapbox when a token is configured, otherwise the
 *  keyless set - the map works either way, and nothing has to be signed up
 *  for to get a working one. */
export function basemapsFor(mapboxToken: string | null | undefined): Record<BasemapId, Basemap> {
  if (!mapboxToken) return KEYLESS
  return {
    street: mapboxStyle('Street', 'streets-v12', mapboxToken),
    satellite: mapboxStyle('Satellite', 'satellite-streets-v12', mapboxToken),
    dark: mapboxStyle('Dark', 'dark-v11', mapboxToken),
  }
}
