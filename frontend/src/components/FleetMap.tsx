import { useEffect, useMemo, useRef, useState } from 'react'
import { AttributionControl, MapContainer, TileLayer, Marker, useMap } from 'react-leaflet'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { useTheme } from '../context/ThemeContext'
import Icon from './Icon'
import './FleetMap.css'

export type MapVehicle = {
  id: number
  name: string
  location?: { lat?: number; lng?: number } | null
}

interface FleetMapProps {
  vehicles: MapVehicle[]
  selectedId: number | null
  onSelect: (id: number) => void
  /** Bumped by the page's recenter button. The map refits whenever this
   *  changes, which is how a control outside the MapContainer reaches the
   *  Leaflet instance living inside it. */
  recenterNonce?: number
}

// Required by the ODbL: OpenStreetMap data has to be credited wherever it
// is shown. Leaflet's own "Leaflet |" prefix is courtesy rather than law,
// and is switched off on the control below.
const OSM_CREDIT =
  '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a>'

// The basemaps on offer, all of them keyless.
//
// This used to be CARTO's light/dark pair. CARTO now requires an API key
// and is retiring its open endpoints, so every tile came back stamped
// "API KEY REQUIRED". Esri's imagery wants registration too. A basemap that
// needs an account is not one this app can ship, so neither is here.
//
// "Dark" is not a separate tile set: OSM publishes one style and it is a
// light one. The dark option inverts it in CSS and rotates the hue back,
// which is the standard trick and holds up on a road map with few
// saturated colours. See .fleet-map.is-dark in FleetMap.css.
//
// OSM's tile usage policy expects light traffic and the attribution above.
// A fleet map at this size sits well inside that; a heavier deployment
// should move to a paid tile host.
type BasemapId = 'street' | 'dark' | 'terrain'

const BASEMAPS: Record<BasemapId, { label: string; url: string; attribution: string; maxZoom: number }> = {
  street: {
    label: 'Street',
    url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
    attribution: OSM_CREDIT,
    maxZoom: 19,
  },
  dark: {
    label: 'Dark',
    url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
    attribution: OSM_CREDIT,
    maxZoom: 19,
  },
  terrain: {
    label: 'Terrain',
    // Elevation is worth seeing on a truck route - a grade is a fuel bill.
    // OpenTopoMap is a volunteer-run server with a modest usage policy, so
    // it is an option rather than the default.
    url: 'https://tile.opentopomap.org/{z}/{x}/{y}.png',
    attribution:
      OSM_CREDIT +
      ', <a href="https://opentopomap.org" target="_blank" rel="noreferrer">OpenTopoMap</a> (CC-BY-SA)',
    maxZoom: 17,
  },
}

// Continental US center - every current customer is a US trucking company
// (see PricingPage/config.py), so this is a more useful default view than
// (0, 0) for the brief moment before any vehicle has reported a GPS fix.
const DEFAULT_CENTER: [number, number] = [39.5, -98.35]
const DEFAULT_ZOOM = 4

type LatLng = [number, number]

function truckDivIcon(selected: boolean) {
  return L.divIcon({
    className: 'fleet-map-marker-wrap',
    html:
      `<div class="fleet-map-marker${selected ? ' is-selected' : ''}">` +
      '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
      'stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h11v10H3zM14 10h4l3 3v3h-7z"/>' +
      '<circle cx="7" cy="18" r="2"/><circle cx="18" cy="18" r="2"/></svg></div>',
    iconSize: [30, 30],
    iconAnchor: [15, 15],
  })
}

// Keeps the viewport framed around whatever vehicles currently have a GPS
// fix. Separate from FleetMap itself because react-leaflet's useMap() only
// works inside a MapContainer's children, not in the component that renders
// the MapContainer.
function ViewportController({
  points,
  focusPoint,
  recenterNonce,
}: {
  points: LatLng[]
  focusPoint: LatLng | null
  recenterNonce: number
}) {
  const map = useMap()
  const pointsKey = points.map((p) => p.join(',')).join('|')

  const frame = () => {
    if (points.length === 0) {
      map.setView(DEFAULT_CENTER, DEFAULT_ZOOM)
      return
    }
    if (points.length === 1) {
      map.setView(points[0], 8)
      return
    }
    map.fitBounds(L.latLngBounds(points), { padding: [48, 48], maxZoom: 10 })
  }

  // Deliberately skips the first render: the map has just framed itself.
  const first = useRef(true)
  useEffect(() => {
    if (first.current) {
      first.current = false
      return
    }
    frame()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recenterNonce])

  useEffect(() => {
    if (points.length === 0) return
    if (points.length === 1) {
      map.setView(points[0], 6)
      return
    }
    map.fitBounds(L.latLngBounds(points), { padding: [48, 48], maxZoom: 10 })
    // pointsKey is the real dependency (a stable string form of points) -
    // the array reference itself changes every poll even when unchanged.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pointsKey])

  useEffect(() => {
    if (focusPoint) map.panTo(focusPoint)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusPoint?.join(',')])

  return null
}

export default function FleetMap({ vehicles, selectedId, onSelect, recenterNonce = 0 }: FleetMapProps) {
  const { resolvedTheme } = useTheme()
  // The app's own theme picks the opening basemap; after that the choice is
  // the reader's, because someone may want the road names legible on a dark
  // dashboard, or the terrain regardless of either.
  const [basemap, setBasemap] = useState<BasemapId>(resolvedTheme === 'dark' ? 'dark' : 'street')
  const [layersOpen, setLayersOpen] = useState(false)
  const tiles = BASEMAPS[basemap]

  const located = useMemo(
    () =>
      vehicles.filter(
        (v): v is MapVehicle & { location: { lat: number; lng: number } } =>
          v.location?.lat != null && v.location?.lng != null
      ),
    [vehicles]
  )
  const points = useMemo<LatLng[]>(() => located.map((v) => [v.location.lat, v.location.lng]), [located])
  const focusVehicle = located.find((v) => v.id === selectedId)
  const focusPoint: LatLng | null = focusVehicle ? [focusVehicle.location.lat, focusVehicle.location.lng] : null

  return (
    <div className="fleet-map-wrap">
      <MapContainer
        center={points[0] ?? DEFAULT_CENTER}
        zoom={points.length ? 6 : DEFAULT_ZOOM}
        className={`fleet-map${basemap === 'dark' ? ' is-dark' : ''}`}
        scrollWheelZoom
        attributionControl={false}
      >
        {/* key forces a fresh layer rather than a re-used one with a
            swapped URL, which Leaflet handles by holding the old tiles
            until every new one has loaded - a visibly torn map. */}
        <TileLayer key={basemap} url={tiles.url} attribution={tiles.attribution} maxZoom={tiles.maxZoom} />
        {/* prefix={false} drops "Leaflet |". The OpenStreetMap credit
            stays: the ODbL requires it, and it has to be visible without
            anyone having to go looking. It is small and out of the way,
            which the guidelines allow - it is not optional. */}
        <AttributionControl position="bottomright" prefix={false} />
        <ViewportController points={points} focusPoint={focusPoint} recenterNonce={recenterNonce} />
        {located.map((vehicle) => (
          <Marker
            key={vehicle.id}
            position={[vehicle.location.lat, vehicle.location.lng]}
            icon={truckDivIcon(vehicle.id === selectedId)}
            eventHandlers={{ click: () => onSelect(vehicle.id) }}
          />
        ))}
      </MapContainer>

      <div className="map-layers">
        <button
          type="button"
          className="map-control"
          onClick={() => setLayersOpen((open) => !open)}
          aria-expanded={layersOpen}
          aria-label="Map style"
          title="Map style"
        >
          <Icon name="layers" size={17} />
        </button>
        {layersOpen && (
          <div className="map-layers-menu" role="radiogroup" aria-label="Map style">
            {(Object.keys(BASEMAPS) as BasemapId[]).map((id) => (
              <button
                key={id}
                type="button"
                role="radio"
                aria-checked={basemap === id}
                className={basemap === id ? 'is-chosen' : undefined}
                onClick={() => {
                  setBasemap(id)
                  setLayersOpen(false)
                }}
              >
                {BASEMAPS[id].label}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
