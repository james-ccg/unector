import { useEffect, useMemo } from 'react'
import { MapContainer, TileLayer, Marker, useMap } from 'react-leaflet'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { useTheme } from '../context/ThemeContext'
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
}

// OpenStreetMap's own tiles, which need no API key and no account.
//
// This used to point at CARTO's basemaps.cartocdn.com light/dark pair,
// chosen because they came as a matching set. CARTO now requires a key for
// those and is retiring the open endpoints, so every tile came back stamped
// "API KEY REQUIRED" across the map.
//
// OSM ships one style, and it is a light one. Rather than take a key for a
// dark twin, the dark theme inverts these in CSS - see .fleet-map.is-dark
// in FleetMap.css. Inversion alone would turn the land cyan, so the hue is
// rotated back 180 degrees, which is the standard trick and holds up well
// on a road map with few saturated colours.
//
// OSM's tile usage policy expects light, non-commercial-scale traffic and
// requires the attribution below. A fleet map at this size sits well inside
// that; a heavier deployment should move to a paid tile host.
const TILES = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
const TILE_ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a> contributors'

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
function ViewportController({ points, focusPoint }: { points: LatLng[]; focusPoint: LatLng | null }) {
  const map = useMap()
  const pointsKey = points.map((p) => p.join(',')).join('|')

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

export default function FleetMap({ vehicles, selectedId, onSelect }: FleetMapProps) {
  const { resolvedTheme } = useTheme()

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
    <MapContainer
      center={points[0] ?? DEFAULT_CENTER}
      zoom={points.length ? 6 : DEFAULT_ZOOM}
      className={`fleet-map${resolvedTheme === 'dark' ? ' is-dark' : ''}`}
      scrollWheelZoom
    >
      <TileLayer url={TILES} attribution={TILE_ATTRIBUTION} maxZoom={19} />
      <ViewportController points={points} focusPoint={focusPoint} />
      {located.map((vehicle) => (
        <Marker
          key={vehicle.id}
          position={[vehicle.location.lat, vehicle.location.lng]}
          icon={truckDivIcon(vehicle.id === selectedId)}
          eventHandlers={{ click: () => onSelect(vehicle.id) }}
        />
      ))}
    </MapContainer>
  )
}
