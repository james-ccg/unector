import type { GroupProfileField } from '../services/api'

/**
 * The eight details a truck's Telegram group description can carry, and
 * what to call them on screen.
 *
 * These live apart from the component that renders them because two places
 * show the same set - the reading waiting to be confirmed, and the form for
 * typing details in by hand - and both must offer exactly the fields the
 * API accepts, in the same order.
 */

export const FIELD_LABELS: Record<GroupProfileField, string> = {
  truck_number: 'Truck #',
  trailer_number: 'Trailer #',
  driver_name: 'Driver',
  driver_phone: 'Phone',
  co_driver_name: 'Co-driver',
  co_driver_phone: 'Co-driver phone',
  vin: 'VIN',
  driver_email: 'Email',
}

// Truck first, then the people, then the identifiers - the order a
// dispatcher reads a group description in.
export const FIELD_ORDER: GroupProfileField[] = [
  'truck_number',
  'trailer_number',
  'driver_name',
  'driver_phone',
  'co_driver_name',
  'co_driver_phone',
  'vin',
  'driver_email',
]
