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
//     CC BY-NC-SA - non-commercial. Freight Pilot is a paid product, so
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

export const BASEMAPS: Record<
  BasemapId,
  { label: string; url: string; attribution: string; maxZoom: number; invert?: boolean }
> = {
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
