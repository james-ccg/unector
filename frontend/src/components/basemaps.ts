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
// Satellite is USGS imagery: public-domain US government aerial photography
// served without a key. It covers the United States only, which is where
// every customer of this app operates. Esri's world imagery would cover
// more, but its current basemap service wants a token, and CARTO now wants
// one too - a basemap that needs an account is not one this app can ship.
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
    url: 'https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/tile/{z}/{y}/{x}',
    attribution:
      'Imagery <a href="https://www.usgs.gov/" target="_blank" rel="noreferrer">USGS</a> - United States only',
    maxZoom: 16,
  },
  dark: {
    label: 'Dark',
    url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
    attribution: OSM_CREDIT,
    maxZoom: 19,
    invert: true,
  },
}
