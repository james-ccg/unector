import { useCallback, useState, useEffect } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { motion, AnimatePresence } from 'motion/react'
import Layout from '../components/Layout'
import Icon from '../components/Icon'
import ErrorMessage from '../components/ErrorMessage'
import PasswordInput from '../components/PasswordInput'
import TwoFactorSettings from '../components/TwoFactorSettings'
import ThemeToggle from '../components/ThemeToggle'
import FontToggle from '../components/FontToggle'
import AvatarPicker from '../components/AvatarPicker'
import Alert from '../components/Alert'
import GroupProfileReview, { FieldGrid } from '../components/GroupProfileReview'
import NotificationSettings from '../components/NotificationSettings'
import { useAuth } from '../context/AuthContext'
import { usePreferences } from '../context/PreferencesContext'
import {
  settingsApi, dashboardApi, billingApi, teamApi, errorMessage,
  type BillingStatus, type SavedPaymentMethod, type AlertRule, type AlertScenario, type CompanySettings, type Dispatcher,
  type Driver, type DriverLinkCode, type GroupProfileField, type GroupProfileProposal,
  type TeamMember, type Truck, type Trailer, type CompanyGroup,
} from '../services/api'
import { PLAN_LABELS, PLAN_PRICE_LABELS } from '../lib/plans'
import {
  CARD_HELD_NOTICE, CARD_REMOVAL_ENDS_PLAN_NOTICE, chargeLabel, isAwaitingPayment, methodLabel,
} from '../lib/billing'
import './DashboardPage.css'
import './SettingsPage.css'
import { gmailErrorMessage } from '../lib/gmailError'

/** Turns an expiry timestamp into something worth reading on a card. Lives
 *  outside the component because it reads the clock - fine in an event
 *  handler, not during render. */
function describeExpiry(iso: string | null | undefined): string {
  if (!iso) return 'soon'
  const hours = (new Date(iso).getTime() - Date.now()) / 3_600_000
  if (hours <= 1) return 'within the hour'
  if (hours < 24) return `in about ${Math.round(hours)} hours`
  return `in ${Math.round(hours / 24)} days`
}

export default function SettingsPage() {
  const { user } = useAuth()
  const { reduceMotion, setReduceMotion } = usePreferences()
  const [searchParams, setSearchParams] = useSearchParams()
  const [settings, setSettings] = useState<CompanySettings | null>(null)
  const [dispatchers, setDispatchers] = useState<Dispatcher[]>([])
  const [loading, setLoading] = useState(true)
  const [banner, setBanner] = useState<{ kind: 'success' | 'error'; text: string } | null>(null)

  const [billing, setBilling] = useState<BillingStatus | null>(null)
  const [billingBusy, setBillingBusy] = useState(false)

  const [team, setTeam] = useState<TeamMember[]>([])

  // Samsara "connect" modal state
  const [samsaraModalOpen, setSamsaraModalOpen] = useState(false)
  const [samsaraKey, setSamsaraKey] = useState('')
  const [samsaraBusy, setSamsaraBusy] = useState(false)
  const [samsaraError, setSamsaraError] = useState('')

  // Add-dispatcher form state
  const [newUsername, setNewUsername] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [addDispatcherError, setAddDispatcherError] = useState('')
  const [addDispatcherBusy, setAddDispatcherBusy] = useState(false)

  // Edit-dispatcher modal state
  const [editDispatcher, setEditDispatcher] = useState<Dispatcher | null>(null)
  const [editUsername, setEditUsername] = useState('')
  const [editPassword, setEditPassword] = useState('')
  const [editDispatcherError, setEditDispatcherError] = useState('')
  const [editDispatcherBusy, setEditDispatcherBusy] = useState(false)

  // Fleet assets - trucks and trailers, managed by either role.
  const [trucks, setTrucks] = useState<Truck[]>([])
  const [trailers, setTrailers] = useState<Trailer[]>([])
  const [newTruckUnit, setNewTruckUnit] = useState('')
  const [newTrailerUnit, setNewTrailerUnit] = useState('')
  const [fleetError, setFleetError] = useState('')
  const [fleetBusy, setFleetBusy] = useState(false)

  // Drivers - self-service creation + Telegram group linking
  const [drivers, setDrivers] = useState<Driver[]>([])
  // Truck/driver details the bot read out of a group description and
  // nobody has confirmed yet. The same readings are sitting in Telegram
  // with Confirm on them, so this list can go stale while the page is
  // open - a 409 on confirm is how we find out, and it is not an error.
  const [groupProfiles, setGroupProfiles] = useState<GroupProfileProposal[]>([])
  // The by-hand path, for carriers who keep nothing in the group description
  // and for fixing a detail later. Writes through the same endpoint that
  // confirming a reading does.
  const [detailsDriverId, setDetailsDriverId] = useState<number | null>(null)
  const [detailsValues, setDetailsValues] = useState<Partial<Record<GroupProfileField, string>>>({})
  const [detailsBusy, setDetailsBusy] = useState(false)
  const [detailsError, setDetailsError] = useState('')
  // Which Telegram group a driver's loads go to. Only groups the company
  // has already linked can be offered here - claiming a new one still means
  // running /linkdriver inside it, which is what proves you are in it.
  const [groupDriverId, setGroupDriverId] = useState<number | null>(null)
  const [companyGroups, setCompanyGroups] = useState<CompanyGroup[]>([])
  const [groupBusy, setGroupBusy] = useState(false)
  const [groupError, setGroupError] = useState('')
  const [newDriverName, setNewDriverName] = useState('')
  const [addDriverError, setAddDriverError] = useState('')
  const [addDriverBusy, setAddDriverBusy] = useState(false)
  const [linkDriverId, setLinkDriverId] = useState<number | null>(null)
  const [linkCode, setLinkCode] = useState<DriverLinkCode | null>(null)
  const [linkBusy, setLinkBusy] = useState(false)

  // Location alert rules
  const [alertRules, setAlertRules] = useState<AlertRule[]>([])
  const [newRuleScenario, setNewRuleScenario] = useState<AlertScenario>('pu_near')
  const [newRuleDistance, setNewRuleDistance] = useState('5')
  const [newRuleMessage, setNewRuleMessage] = useState('')
  const [alertRuleError, setAlertRuleError] = useState('')
  const [alertRuleBusy, setAlertRuleBusy] = useState(false)

  const isOwner = user?.role === 'owner'

  // Gmail connection health. 'expiring' exists because Google revokes the
  // refresh tokens of an app still in review after 7 days - warning only once
  // it's already dead means the owner finds out from a driver asking where
  // their load went.
  const gmailState = settings?.gmail_state ?? (settings?.gmail_needs_reconnect ? 'expired' : 'ok')
  const needsReconnect = gmailState === 'expired' || gmailState === 'expiring'
  // Phrased once when settings arrive rather than on every render: reading
  // the clock during render makes the output depend on when React happened
  // to re-run, which is exactly what the purity rule is guarding against.
  const [gmailExpiresIn, setGmailExpiresIn] = useState('soon')

  // Nine tabs wrapped onto two rows, which is where a tab bar stops being
  // navigation and starts being a list to read. Grouped into five related
  // panels instead - the individual sections below are untouched, they just
  // share a tab now. Every tab shows for both roles; the owner-only sections
  // inside keep their own guards, so a dispatcher opening People simply sees
  // Team and nothing else.
  type SettingsSection = 'company' | 'preferences' | 'notifications' | 'billing' | 'integrations' | 'alerts' | 'fleet' | 'drivers' | 'dispatchers' | 'team' | 'security'
  type SettingsTab = 'general' | 'billing' | 'integrations' | 'fleet' | 'people' | 'security'

  const TAB_SECTIONS: Record<SettingsTab, SettingsSection[]> = {
    general: ['company', 'preferences', 'notifications'],
    billing: ['billing'],
    integrations: ['integrations', 'alerts'],
    fleet: ['fleet', 'drivers'],
    people: ['dispatchers', 'team'],
    security: ['security'],
  }

  /* Which tab a #hash belongs to.
   *
   * The tabs hide their sections rather than unmounting them, so a link to
   * #gmail scrolled to a card that was sitting behind display:none - the
   * page opened on General and the reader saw no reason the link had done
   * anything. Anything deep-linkable has to say which tab holds it. */
  const TAB_FOR_HASH: Record<string, SettingsTab> = {
    gmail: 'integrations',
    samsara: 'integrations',
  }

  const initialTab = TAB_FOR_HASH[window.location.hash.slice(1)] ?? 'general'
  const [activeTab, setActiveTab] = useState<SettingsTab>(initialTab)
  const SETTINGS_NAV: { key: SettingsTab; label: string; icon: Parameters<typeof Icon>[0]['name'] }[] = [
    { key: 'general', label: 'General', icon: 'briefcase' },
    { key: 'fleet', label: 'Fleet', icon: 'truck' },
    { key: 'people', label: 'People', icon: 'users' },
    { key: 'integrations', label: 'Integrations', icon: 'email' },
    { key: 'billing', label: 'Billing', icon: 'money' },
    { key: 'security', label: 'Security', icon: 'shield' },
  ]

  /** Class for a section block - visible when its tab is the active one. */
  const sectionClass = (section: SettingsSection) =>
    `settings-section ${TAB_SECTIONS[activeTab].includes(section) ? '' : 'settings-section-hidden'}`

  useEffect(() => {
    const onHashChange = () => {
      const tab = TAB_FOR_HASH[window.location.hash.slice(1)]
      if (tab) setActiveTab(tab)
    }
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const loadAll = async () => {
    if (!user) return
    try {
      const settingsData = await settingsApi.getSettings()
      setSettings(settingsData)
      setGmailExpiresIn(describeExpiry(settingsData.gmail_expires_at))
      // Billing is shared: whoever's paying (owner or dispatcher) can view
      // and manage the plan, so this loads regardless of role.
      const billingData = await billingApi.getStatus()
      setBilling(billingData)
      const teamData = await teamApi.list()
      setTeam(teamData)
      // Fleet and drivers load for both roles - keeping the board current is
      // dispatch work, not an ownership decision.
      setTrucks(await dashboardApi.listTrucks())
      setTrailers(await dashboardApi.listTrailers())
      setDrivers(await dashboardApi.listDrivers())
      setGroupProfiles(await dashboardApi.listGroupProfiles())
      if (user.role === 'owner') {
        const dispatcherData = await dashboardApi.listDispatchers()
        setDispatchers(dispatcherData)
        const alertRuleData = await settingsApi.listAlertRules()
        setAlertRules(alertRuleData)
      }
    } catch (err) {
      console.error(err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    // loadAll is a shared refresh function (also called after every
    // mutation below - connect Gmail, add dispatcher, toggle an alert rule,
    // etc.), not something that only ever runs on mount - inlining it here
    // would duplicate that logic for no benefit.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadAll()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Handle the redirect back from Google's OAuth consent screen
  // (?gmail=connected / ?gmail=error / ?gmail=error_no_refresh_token)
  useEffect(() => {
    const gmailStatus = searchParams.get('gmail')
    if (!gmailStatus) return

    // Deferred a tick so the banner update isn't a same-render-cycle setState
    // (react-hooks/set-state-in-effect) - purely cosmetic timing-wise, since
    // a microtask still runs before the next paint.
    queueMicrotask(() => {
      if (gmailStatus === 'connected') {
        setBanner({ kind: 'success', text: 'Gmail connected successfully.' })
        loadAll()
      } else {
        const text = gmailErrorMessage(gmailStatus, searchParams.get('reason'))
        if (text) setBanner({ kind: 'error', text })
      }
    })

    searchParams.delete('gmail')
    setSearchParams(searchParams, { replace: true })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Saved payment methods. Owner-only on the server, so a dispatcher never
  // sees this section at all.
  const [paymentMethods, setPaymentMethods] = useState<SavedPaymentMethod[]>([])

  // Two different things can be true of the only card on file, and they
  // need different words. While the current period is unpaid it cannot come
  // off at all - it is the only way the amount owed can be collected. Once
  // it has been paid, it can, and doing so ends the plan at the end of the
  // period already bought. Both are worked out here so the button says so
  // before it is pressed rather than the server answering afterwards.
  const onlyCard = paymentMethods.length === 1
  const cardIsHeld = onlyCard && isAwaitingPayment(billing?.status)
  const removingEndsPlan = onlyCard && billing?.status === 'active'
  const [cardBusy, setCardBusy] = useState(false)
  // Shown inside the billing card, not in the page-top banner. This
  // section is far down a long page - an error announced at the top is
  // an error nobody standing here can see.
  const [cardError, setCardError] = useState('')

  const loadPaymentMethods = useCallback(async () => {
    if (!isOwner) return
    try {
      const { payment_methods } = await billingApi.listPaymentMethods()
      setPaymentMethods(payment_methods)
    } catch {
      // Nothing the owner can do about it, and it must not take the rest
      // of the billing section down with it.
    }
  }, [isOwner])

  useEffect(() => {
    // The fetch resolves after the effect has run, so the setState inside
    // it is not synchronous with the effect.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadPaymentMethods()
  }, [loadPaymentMethods])

  const handleAddPaymentMethod = async () => {
    setCardBusy(true)
    setCardError('')
    try {
      const { url } = await billingApi.startPaymentMethodSetup()
      window.location.href = url
    } catch (err) {
      setCardError(errorMessage(err, "Couldn't open the payment form."))
      setCardBusy(false)
    }
  }

  const handleRemovePaymentMethod = async (id: string) => {
    setCardBusy(true)
    setCardError('')
    try {
      const result = await billingApi.removePaymentMethod(id)
      await loadPaymentMethods()
      await loadAll()
      if (result.cancelled_at_period_end) {
        // That was the only one left, so the plan now runs to the end of
        // what was already paid for. Said here rather than left to be
        // discovered from a later email.
        const until = result.plan_ends_at
          ? ` You keep your plan until ${new Date(result.plan_ends_at).toLocaleDateString()}.`
          : ' You keep your plan until the period you have paid for runs out.'
        setBanner({
          kind: 'success',
          text: `Payment method removed.${until} Nothing will be charged again.`,
        })
      } else {
        setBanner({ kind: 'success', text: 'Payment method removed.' })
      }
    } catch (err) {
      setCardError(errorMessage(err, "Couldn't remove that payment method."))
    } finally {
      setCardBusy(false)
    }
  }

  // Handle the redirect back from Stripe Checkout (?billing=success)
  useEffect(() => {
    const billingStatus = searchParams.get('billing')
    if (!billingStatus) return

    if (billingStatus === 'success') {
      queueMicrotask(() => {
        setBanner({ kind: 'success', text: 'Subscription started. It may take a few seconds to appear below.' })
        loadAll()
      })
    }

    // Coming back from the save-a-card page. Stripe has already attached
    // it; this just reloads the list and says so.
    if (billingStatus === 'card_saved') {
      queueMicrotask(() => {
        setBanner({ kind: 'success', text: 'Payment method saved.' })
        void loadPaymentMethods()
      })
    }

    searchParams.delete('billing')
    setSearchParams(searchParams, { replace: true })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const handleManageBilling = async () => {
    if (!user) return
    setBillingBusy(true)
    try {
      const { url } = await billingApi.openPortal()
      window.location.href = url
    } catch (err) {
      setBanner({ kind: 'error', text: errorMessage(err, "Couldn't open the billing portal.") })
      setBillingBusy(false)
    }
  }

  const handleConnectGmail = async () => {
    if (!user) return
    try {
      const { auth_url } = await settingsApi.getGmailAuthUrl()
      // Full-page redirect to Google's own consent screen - no code to copy/paste.
      window.location.href = auth_url
    } catch (err) {
      setBanner({ kind: 'error', text: errorMessage(err, "Couldn't start the Gmail connection.") })
    }
  }

  const handleDisconnectGmail = async () => {
    if (!user) return
    if (!confirm('Disconnect Gmail? The bot will stop being able to find Rate Confirmation emails until you reconnect.')) return
    try {
      await settingsApi.disconnectGmail()
      setBanner({ kind: 'success', text: 'Gmail disconnected.' })
      loadAll()
    } catch (err) {
      setBanner({ kind: 'error', text: errorMessage(err) })
    }
  }

  const handleConnectSamsara = async () => {
    if (!user || !samsaraKey.trim()) return
    setSamsaraBusy(true)
    setSamsaraError('')
    try {
      await settingsApi.connectSamsara(samsaraKey.trim())
      setSamsaraModalOpen(false)
      setSamsaraKey('')
      setBanner({ kind: 'success', text: 'Samsara connected successfully.' })
      loadAll()
    } catch (err) {
      setSamsaraError(errorMessage(err, "Couldn't connect Samsara. Double-check the API token."))
    } finally {
      setSamsaraBusy(false)
    }
  }

  const handleDisconnectSamsara = async () => {
    if (!user) return
    if (!confirm('Disconnect Samsara? GPS proximity alerts will stop working until you reconnect.')) return
    try {
      await settingsApi.disconnectSamsara()
      setBanner({ kind: 'success', text: 'Samsara disconnected.' })
      loadAll()
    } catch (err) {
      setBanner({ kind: 'error', text: errorMessage(err) })
    }
  }

  const handleAddDispatcher = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!user) return
    setAddDispatcherError('')
    if (newPassword.length < 6) {
      setAddDispatcherError('Password must be at least 6 characters.')
      return
    }
    setAddDispatcherBusy(true)
    try {
      await dashboardApi.addDispatcher(newUsername.trim(), newPassword)
      setNewUsername('')
      setNewPassword('')
      setBanner({ kind: 'success', text: 'Dispatcher login created.' })
      loadAll()
    } catch (err) {
      setAddDispatcherError(errorMessage(err, "Couldn't create that dispatcher login."))
    } finally {
      setAddDispatcherBusy(false)
    }
  }

  const openEditDispatcher = (d: Dispatcher) => {
    setEditDispatcher(d)
    setEditUsername(d.username)
    setEditPassword('')
    setEditDispatcherError('')
  }

  const handleSaveDispatcherEdit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!editDispatcher) return
    setEditDispatcherError('')

    const username = editUsername.trim()
    if (!username) {
      setEditDispatcherError('Username cannot be empty.')
      return
    }
    if (editPassword && editPassword.length < 6) {
      setEditDispatcherError('Password must be at least 6 characters.')
      return
    }

    setEditDispatcherBusy(true)
    try {
      const updates: { username?: string; password?: string } = {}
      if (username !== editDispatcher.username) updates.username = username
      if (editPassword) updates.password = editPassword
      await dashboardApi.updateDispatcher(editDispatcher.id, updates)
      setEditDispatcher(null)
      setBanner({ kind: 'success', text: 'Dispatcher login updated.' })
      loadAll()
    } catch (err) {
      setEditDispatcherError(errorMessage(err, "Couldn't update that dispatcher login."))
    } finally {
      setEditDispatcherBusy(false)
    }
  }

  const handleDeleteDispatcher = async (d: Dispatcher) => {
    if (!confirm(`Remove dispatcher login "${d.username}"? They'll lose access immediately.`)) return
    try {
      await dashboardApi.deleteDispatcher(d.id)
      setBanner({ kind: 'success', text: 'Dispatcher login removed.' })
      loadAll()
    } catch (err) {
      setBanner({ kind: 'error', text: errorMessage(err, "Couldn't remove that dispatcher login.") })
    }
  }

  /** Every fleet mutation goes through here: they all share the same
   *  busy/error handling and all end by refreshing the lists, so the UI can
   *  never drift from what the server actually holds. */
  const runFleetAction = async (action: () => Promise<unknown>, fallback: string) => {
    setFleetBusy(true)
    setFleetError('')
    try {
      await action()
      setTrucks(await dashboardApi.listTrucks())
      setTrailers(await dashboardApi.listTrailers())
      setDrivers(await dashboardApi.listDrivers())
      return true
    } catch (err) {
      setFleetError(errorMessage(err, fallback))
      return false
    } finally {
      setFleetBusy(false)
    }
  }

  const handleAddTruck = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!newTruckUnit.trim()) return
    const ok = await runFleetAction(
      () => dashboardApi.createTruck(newTruckUnit.trim()), "Couldn't add that truck.",
    )
    if (ok) setNewTruckUnit('')
  }

  const handleAddTrailer = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!newTrailerUnit.trim()) return
    const ok = await runFleetAction(
      () => dashboardApi.createTrailer(newTrailerUnit.trim()), "Couldn't add that trailer.",
    )
    if (ok) setNewTrailerUnit('')
  }

  const handleDeleteTruck = (truck: Truck) => {
    if (!window.confirm(`Delete truck ${truck.unit_number}? Its driver stays, and is unassigned.`)) return
    runFleetAction(() => dashboardApi.deleteTruck(truck.id), "Couldn't delete that truck.")
  }

  const handleDeleteTrailer = (trailer: Trailer) => {
    if (!window.confirm(`Delete trailer ${trailer.unit_number}?`)) return
    runFleetAction(() => dashboardApi.deleteTrailer(trailer.id), "Couldn't delete that trailer.")
  }

  const handleDeleteDriver = (driver: Driver) => {
    if (!window.confirm(`Remove ${driver.full_name || driver.driver_bot_id}?`)) return
    runFleetAction(() => dashboardApi.deleteDriver(driver.id), "Couldn't remove that driver.")
  }

  const handleAddDriver = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!user) return
    setAddDriverError('')
    const name = newDriverName.trim()
    if (!name) {
      setAddDriverError('Driver name is required.')
      return
    }
    setAddDriverBusy(true)
    try {
      const created = await dashboardApi.createDriver(name)
      setNewDriverName('')
      setBanner({ kind: 'success', text: `${created.full_name} added.` })
      // A driver starts unassigned - a truck is put against them afterwards,
      // from the Fleet tab.
      setDrivers((prev) => [...prev, {
        ...created,
        dispatcher_username: null,
        samsara_vehicle_id: null,
        truck: null,
        trailer: null,
        // Filled in later, either from the group's description or by hand.
        phone: null,
        email: null,
        co_driver_name: null,
        co_driver_phone: null,
        vin: null,
        load_count: 0,
        weekly_gross: 0,
        weekly_loads: 0,
      }])
      setLinkDriverId(created.id)
      setLinkCode({ code: created.link_code, bot_command: created.bot_command })
    } catch (err) {
      setAddDriverError(errorMessage(err, "Couldn't add that driver."))
    } finally {
      setAddDriverBusy(false)
    }
  }

  const handleGroupProfileResolved = async (id: number, message: string) => {
    setGroupProfiles((prev) => prev.filter((p) => p.id !== id))
    setBanner({ kind: 'success', text: message })
    try {
      setDrivers(await dashboardApi.listDrivers())
      setTrucks(await dashboardApi.listTrucks())
      setTrailers(await dashboardApi.listTrailers())
    } catch (err) {
      // The save itself went through; only the refresh failed, so say that
      // rather than implying the details were lost.
      setBanner({ kind: 'error', text: errorMessage(err, "Saved, but the page couldn't refresh.") })
    }
  }

  // Opening the panel is what loads the group list - it is only useful
  // while the panel is open, and a company with one truck should not pay
  // for the request on every visit to Settings.
  const openDriverGroup = async (driver: Driver) => {
    if (groupDriverId === driver.id) {
      setGroupDriverId(null)
      return
    }
    setGroupError('')
    setGroupDriverId(driver.id)
    setGroupBusy(true)
    try {
      const { groups } = await dashboardApi.listGroups()
      setCompanyGroups(groups)
    } catch (err) {
      setGroupError(errorMessage(err, "Couldn't load this company's groups."))
    } finally {
      setGroupBusy(false)
    }
  }

  const applyDriverGroup = async (driverId: number, telegramGroupId: number | null) => {
    setGroupBusy(true)
    setGroupError('')
    try {
      await dashboardApi.setDriverGroup(driverId, telegramGroupId)
      const [fresh, { groups }] = await Promise.all([
        dashboardApi.listDrivers(),
        dashboardApi.listGroups(),
      ])
      setDrivers(fresh)
      setCompanyGroups(groups)
      setBanner({
        kind: 'success',
        text: telegramGroupId === null ? 'Group unlinked.' : 'Group moved.',
      })
      setGroupDriverId(null)
    } catch (err) {
      setGroupError(errorMessage(err, "Couldn't change that driver's group."))
    } finally {
      setGroupBusy(false)
    }
  }

  const openDriverDetails = (driver: Driver) => {
    if (detailsDriverId === driver.id) {
      setDetailsDriverId(null)
      return
    }
    setDetailsError('')
    setDetailsDriverId(driver.id)
    setDetailsValues({
      truck_number: driver.truck?.unit_number ?? '',
      trailer_number: driver.trailer?.unit_number ?? '',
      driver_name: driver.full_name ?? '',
      driver_phone: driver.phone ?? '',
      co_driver_name: driver.co_driver_name ?? '',
      co_driver_phone: driver.co_driver_phone ?? '',
      vin: driver.vin ?? '',
      driver_email: driver.email ?? '',
    })
  }

  const handleSaveDriverDetails = async (driverId: number) => {
    // Only send what has something in it. An empty box means "not known",
    // not "clear what is on file" - clearing is not what this form is for.
    const filled = Object.fromEntries(
      Object.entries(detailsValues).filter(([, v]) => (v ?? '').trim() !== '')
    ) as Partial<Record<GroupProfileField, string>>

    if (Object.keys(filled).length === 0) {
      setDetailsError('Fill in at least one detail before saving.')
      return
    }

    setDetailsBusy(true)
    setDetailsError('')
    try {
      await dashboardApi.saveDriverDetails(driverId, filled)
      setDrivers(await dashboardApi.listDrivers())
      setTrucks(await dashboardApi.listTrucks())
      setTrailers(await dashboardApi.listTrailers())
      setDetailsDriverId(null)
      setBanner({ kind: 'success', text: 'Details saved.' })
    } catch (err) {
      setDetailsError(errorMessage(err, "Couldn't save these details."))
    } finally {
      setDetailsBusy(false)
    }
  }

  const handleShowLinkCode = async (driverId: number) => {
    setLinkBusy(true)
    try {
      const code = await dashboardApi.createDriverLinkToken(driverId)
      setLinkDriverId(driverId)
      setLinkCode(code)
    } catch (err) {
      setBanner({ kind: 'error', text: errorMessage(err, "Couldn't generate a linking code.") })
    } finally {
      setLinkBusy(false)
    }
  }

  const handleCheckDriverLinked = async (driverId: number) => {
    setLinkBusy(true)
    try {
      const fresh = await dashboardApi.listDrivers()
      setDrivers(fresh)
      const updated = fresh.find((d) => d.id === driverId)
      if (updated?.telegram_group_id) {
        setLinkDriverId(null)
        setLinkCode(null)
        setBanner({ kind: 'success', text: `${updated.full_name} is linked to ${updated.telegram_group_title || 'its Telegram group'}.` })
      }
    } catch (err) {
      setBanner({ kind: 'error', text: errorMessage(err) })
    } finally {
      setLinkBusy(false)
    }
  }

  const handleAddAlertRule = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!user) return
    setAlertRuleError('')
    const distance = parseFloat(newRuleDistance)
    if (!distance || distance <= 0 || distance > 500) {
      setAlertRuleError('Enter a distance between 0 and 500 miles.')
      return
    }
    setAlertRuleBusy(true)
    try {
      const rule = await settingsApi.createAlertRule(newRuleScenario, distance, newRuleMessage.trim() || null)
      setAlertRules((prev) => [...prev, rule])
      setNewRuleDistance('5')
      setNewRuleMessage('')
    } catch (err) {
      setAlertRuleError(errorMessage(err, "Couldn't create that rule."))
    } finally {
      setAlertRuleBusy(false)
    }
  }

  const handleToggleAlertRule = async (rule: AlertRule) => {
    try {
      const updated = await settingsApi.updateAlertRule(rule.id, { enabled: !rule.enabled })
      setAlertRules((prev) => prev.map((r) => (r.id === rule.id ? updated : r)))
    } catch (err) {
      setBanner({ kind: 'error', text: errorMessage(err, "Couldn't update that rule.") })
    }
  }

  const handleDeleteAlertRule = async (rule: AlertRule) => {
    if (!confirm(`Delete this ${rule.distance_miles}mi alert rule?`)) return
    try {
      await settingsApi.deleteAlertRule(rule.id)
      setAlertRules((prev) => prev.filter((r) => r.id !== rule.id))
    } catch (err) {
      setBanner({ kind: 'error', text: errorMessage(err, "Couldn't delete that rule.") })
    }
  }

  if (loading) {
    return (
      <Layout>
        <div className="dashboard-page">
          <div className="loading-state">
            <div className="spinner"></div>
            <p>Loading...</p>
          </div>
        </div>
      </Layout>
    )
  }

  const puAlertRules = alertRules.filter((r) => r.scenario === 'pu_near').sort((a, b) => b.distance_miles - a.distance_miles)
  const delAlertRules = alertRules.filter((r) => r.scenario === 'del_near').sort((a, b) => b.distance_miles - a.distance_miles)

  const renderAlertRuleRow = (rule: AlertRule) => (
    <div key={rule.id} className={`alert-rule-row ${rule.enabled ? '' : 'is-disabled'}`}>
      <span className="alert-rule-distance">{rule.distance_miles} mi</span>
      <span className="alert-rule-message">{rule.message_template || 'Standard message'}</span>
      <button className="btn btn-ghost btn-sm" onClick={() => handleToggleAlertRule(rule)}>
        {rule.enabled ? 'Disable' : 'Enable'}
      </button>
      <button className="btn btn-danger-ghost btn-sm" onClick={() => handleDeleteAlertRule(rule)}>
        Remove
      </button>
    </div>
  )

  return (
    <Layout>
    <div className="dashboard-page">
      <div className="dashboard-content container settings-content">
        <header className="page-head">
          <div>
            <p className="eyebrow">{settings?.company_name || '—'}</p>
            <h1>Settings</h1>
          </div>
          {/* Sign out lives in the header's profile menu only - see the note
              on DashboardPage's page-head-actions. */}
          <div className="page-head-actions">
            <Link to="/dashboard" className="btn btn-ghost">
              <Icon name="arrow-left" size={16} /> Dashboard
            </Link>
          </div>
        </header>
        {banner && (
          <Alert kind={banner.kind} onDismiss={() => setBanner(null)}>
            {banner.text}
          </Alert>
        )}

        {!isOwner && (
          <Alert kind="info">
            You're signed in as a dispatcher. Integrations and dispatcher management are owner-only.
          </Alert>
        )}

        <nav className="settings-nav">
          {SETTINGS_NAV.map((item) => (
            <button
              key={item.key}
              type="button"
              className={`settings-nav-item ${activeTab === item.key ? 'is-active' : ''}`}
              onClick={() => setActiveTab(item.key)}
            >
              <Icon name={item.icon} size={16} /> {item.label}
            </button>
          ))}
        </nav>

        {/* ---------------- Company info ---------------- */}
        <section className={sectionClass('company')}>
          <h2 className="section-title">Company</h2>
          <div className="card">
            <div className="settings-row">
              <div>
                <p className="settings-row-label">Company name</p>
                <p className="settings-row-value">{settings?.company_name || '—'}</p>
              </div>
            </div>
            <div className="settings-row">
              <div>
                <p className="settings-row-label">MC number</p>
                <p className="settings-row-value mono">{settings?.mc_number || '—'}</p>
              </div>
            </div>
          </div>
        </section>

        {/* ---------------- App Preferences ---------------- */}
        <section className={sectionClass('preferences')}>
          <h2 className="section-title">App Preferences</h2>
          <div className="card">
            <div className="pref-row">
              <div>
                <p className="settings-row-label">
                  {user?.role === 'owner' ? 'Company logo' : 'Profile picture'}
                </p>
                <p className="settings-row-hint">
                  {user?.role === 'owner'
                    ? "Your carrier's mark. It appears in the dashboard, and the bot puts it on each truck's Telegram group."
                    : 'Shown in your profile menu and to your teammates.'}
                </p>
              </div>
              <AvatarPicker />
            </div>
            <div className="pref-row">
              <div>
                <p className="settings-row-label">What we store</p>
                <p className="settings-row-hint">
                  Change what Unector keeps in this browser. Withdrawing a choice clears
                  what was stored under it.
                </p>
              </div>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => window.dispatchEvent(new CustomEvent('fp:open-consent'))}
              >
                Review
              </button>
            </div>
            <div className="pref-row">
              <div>
                <p className="settings-row-label">Appearance</p>
                <p className="settings-row-hint">Auto matches your device's setting, or the time of day if it doesn't have one.</p>
              </div>
              <ThemeToggle />
            </div>
            <div className="pref-row">
              <div>
                <p className="settings-row-label">Interface font</p>
                <p className="settings-row-hint">The typeface used across the dashboard.</p>
              </div>
              <FontToggle />
            </div>
            <div className="pref-row">
              <div>
                <p className="settings-row-label">Motion</p>
                <p className="settings-row-hint">Reduce animation in page transitions and other interface elements.</p>
              </div>
              <label className="switch">
                <input
                  type="checkbox"
                  checked={reduceMotion}
                  onChange={(e) => setReduceMotion(e.target.checked)}
                  aria-label="Reduce motion"
                />
                <span className="switch-track"><span className="switch-thumb" /></span>
              </label>
            </div>
          </div>
        </section>

        {/* ---------------- Billing ---------------- */}
        {billing && (
          <section className={sectionClass('billing')}>
            <h2 className="section-title">Billing</h2>
            <div className="card billing-card">
              <div className="billing-row">
                <span className="billing-label">Plan</span>
                <span className="billing-value">
                  {PLAN_LABELS[billing.tier] || billing.tier}
                  {billing.tier !== 'free' && ` — ${PLAN_PRICE_LABELS[billing.tier]}`}
                </span>
              </div>
              <div className="billing-row billing-total">
                <span className="billing-label">Active drivers</span>
                <span className="billing-value">{billing.active_drivers} / {billing.max_drivers}</span>
              </div>
              <div className="billing-row billing-total">
                <span className="billing-label">Dispatcher logins</span>
                <span className="billing-value">
                  {billing.dispatchers} / {billing.max_dispatchers ?? 'unlimited'}
                </span>
              </div>
              {billing.status === 'trialing' && billing.trial_ends_at && (
                <p className="billing-hint billing-notice">
                  <strong>Your trial ends {new Date(billing.trial_ends_at).toLocaleDateString()}.</strong>{' '}
                  On that day {chargeLabel(billing.tier, billing.billing_interval) ?? 'your plan'} is
                  charged automatically to the card on file, and again every{' '}
                  {billing.billing_interval === 'year' ? 'year' : 'month'} after that, until you
                  cancel. Cancel any time from Manage billing - before that date, nothing is charged.
                  Until then your payment method stays on file: it can&apos;t be removed while the
                  trial is running, because it is the only way the first payment can be taken.
                </p>
              )}
              {billing.status === 'past_due' && (
                <p className="billing-hint">Your last payment failed. Update your card to keep your plan active.</p>
              )}
              <div className="integration-actions" style={{ marginTop: 16 }}>
                {billing.tier === 'free' ? (
                  <Link to="/pages/pricing" className="btn btn-primary">Upgrade plan</Link>
                ) : (
                  <button className="btn btn-primary" onClick={handleManageBilling} disabled={billingBusy}>
                    {billingBusy ? 'Opening...' : 'Manage billing'}
                  </button>
                )}
              </div>
            </div>

            {/* Payment methods, separate from the plan on purpose. A card
                can be put on file on the free plan and taken off again -
                it is not something that only exists because a subscription
                does. Owner only; the server enforces that too. */}
            {isOwner && (
              <div className="card billing-card">
                <div className="billing-row">
                  <span className="billing-label">Payment method</span>
                </div>

                {paymentMethods.length === 0 ? (
                  <p className="billing-hint">
                    Nothing saved. You don&apos;t need one to use the free plan. Card, PayPal
                    and the wallets Stripe offers all work here, and one can be added whenever
                    you like - a paid plan asks for one when you start it.
                  </p>
                ) : (
                  <ul className="payment-methods">
                    {paymentMethods.map((method) => (
                      <li key={method.id}>
                        <div>
                          <span className="payment-method-name">
                            {methodLabel(method.type, method.brand)}
                            {method.last4 && (
                              <span className="payment-method-digits"> •••• {method.last4}</span>
                            )}
                          </span>
                          {method.exp_month && method.exp_year && (
                            <span className="payment-method-expiry">
                              Expires {String(method.exp_month).padStart(2, '0')}/{method.exp_year}
                            </span>
                          )}
                        </div>
                        <div className="payment-method-actions">
                          {method.is_default && <span className="payment-method-tag">Default</span>}
                          <button
                            type="button"
                            className="btn btn-danger-ghost btn-sm"
                            onClick={() => handleRemovePaymentMethod(method.id)}
                            /* Blocked only while the period is unpaid. When removal is
                               allowed but ends the plan, the button works and the
                               consequence is spelled out under the list instead. */
                            disabled={cardBusy || cardIsHeld}
                            title={
                              cardIsHeld
                                ? CARD_HELD_NOTICE
                                : removingEndsPlan
                                  ? CARD_REMOVAL_ENDS_PLAN_NOTICE
                                  : undefined
                            }
                          >
                            Remove
                          </button>
                        </div>
                      </li>
                    ))}
                  </ul>
                )}

                {cardError && (
                  <Alert kind="error" onDismiss={() => setCardError('')}>
                    {cardError}
                  </Alert>
                )}

                <div className="integration-actions" style={{ marginTop: 16 }}>
                  <button
                    type="button"
                    className="btn btn-ghost"
                    onClick={handleAddPaymentMethod}
                    disabled={cardBusy}
                  >
                    {cardBusy ? 'Opening...' : 'Add payment method'}
                  </button>
                </div>

                {cardIsHeld && (
                  <p className="billing-hint billing-notice" style={{ marginTop: 12 }}>
                    {CARD_HELD_NOTICE}
                  </p>
                )}

                {removingEndsPlan && (
                  <p className="billing-hint billing-notice" style={{ marginTop: 12 }}>
                    {CARD_REMOVAL_ENDS_PLAN_NOTICE}
                  </p>
                )}

                <p className="billing-hint">
                  Card details go straight to Stripe and are never seen or stored by Unector.
                </p>
              </div>
            )}
          </section>
        )}

        {/* ---------------- Integrations ---------------- */}
        <section className={sectionClass('integrations')}>
          <h2 className="section-title">Integrations</h2>

          <div className="card integration-card" id="gmail">
            <div className="integration-header">
              <div className="integration-icon"><Icon name="email" size={22} /></div>
              <div className="integration-info">
                <h3>Gmail</h3>
                <p>Automatically finds rate confirmations in this inbox and sends PODs to brokers.</p>
              </div>
              {/* Three states, not two: a stored token that Google has since
                  revoked still counts as "connected", but nothing works -
                  showing it as plain Connected is what made the dashboard's
                  "reconnect it in Settings" banner lead to a dead end. */}
              <span
                className={`status-badge ${
                  gmailState === 'expired'
                    ? 'is-error'
                    : gmailState === 'expiring'
                      ? 'is-warning'
                      : settings?.gmail_connected
                        ? 'is-connected'
                        : 'is-disconnected'
                }`}
              >
                {gmailState === 'expired'
                  ? 'Disconnected'
                  : gmailState === 'expiring'
                    ? 'Expires soon'
                    : settings?.gmail_connected
                      ? 'Connected'
                      : 'Not connected'}
              </span>
            </div>
            {gmailState === 'expired' && (
              <p className="integration-warning">
                Google has stopped accepting this connection, so rate confirmations aren&apos;t being
                read. Reconnecting takes a few seconds and fixes it.
              </p>
            )}
            {gmailState === 'expiring' && (
              <p className="integration-warning">
                This connection expires {gmailExpiresIn}. Google revokes access for apps still in
                review, so reconnect before then to keep rate confirmations flowing.
              </p>
            )}
            <div className="integration-actions">
              {/* Reconnect is only offered when it would actually achieve
                  something - the connection is dead, or about to be. On a
                  healthy connection the only action is Disconnect, so the
                  card doesn't push a fix for a problem nobody has. */}
              {!settings?.gmail_connected ? (
                <button className="btn btn-primary" onClick={handleConnectGmail} disabled={!isOwner}>
                  Connect Gmail
                </button>
              ) : (
                <>
                  {needsReconnect && (
                    <button className="btn btn-primary" onClick={handleConnectGmail} disabled={!isOwner}>
                      Reconnect Gmail
                    </button>
                  )}
                  <button className="btn btn-danger-ghost" onClick={handleDisconnectGmail} disabled={!isOwner}>
                    Disconnect
                  </button>
                </>
              )}
            </div>
          </div>

          <div className="card integration-card" id="samsara">
            <div className="integration-header">
              <div className="integration-icon"><Icon name="location" size={22} /></div>
              <div className="integration-info">
                <h3>Samsara GPS</h3>
                <p>Powers proximity alerts ("driver is 5 miles from pickup") in the Telegram group.</p>
              </div>
              <span className={`status-badge ${settings?.samsara_connected ? 'is-connected' : 'is-disconnected'}`}>
                {settings?.samsara_connected ? 'Connected' : 'Not connected'}
              </span>
            </div>
            <div className="integration-actions">
              {settings?.samsara_connected ? (
                <button className="btn btn-danger-ghost" onClick={handleDisconnectSamsara} disabled={!isOwner}>
                  Disconnect
                </button>
              ) : (
                <button className="btn btn-primary" onClick={() => setSamsaraModalOpen(true)} disabled={!isOwner}>
                  Connect Samsara
                </button>
              )}
            </div>
          </div>
        </section>

        {/* ---------------- Location alerts ---------------- */}
        {isOwner && (
          <section className={sectionClass('alerts')}>
            <h2 className="section-title">Location alerts</h2>
            <div className="card">
              <p className="settings-hint">
                Choose what the driver's group is told as the truck nears pickup or delivery. Add more than
                one distance per scenario (e.g. a heads-up at 50 miles, then again at 5) - each fires once,
                independently, as the truck gets closer. A scenario with no rules keeps the default: one alert
                with a standard message.
              </p>

              <div className="alert-rule-group">
                <h3 className="settings-subtitle">Near pickup</h3>
                {puAlertRules.length === 0 ? (
                  <p className="empty">Using the default alert.</p>
                ) : (
                  <div className="alert-rule-list">{puAlertRules.map(renderAlertRuleRow)}</div>
                )}
              </div>

              <div className="alert-rule-group">
                <h3 className="settings-subtitle">Near delivery</h3>
                {delAlertRules.length === 0 ? (
                  <p className="empty">Using the default alert.</p>
                ) : (
                  <div className="alert-rule-list">{delAlertRules.map(renderAlertRuleRow)}</div>
                )}
              </div>

              <form className="form alert-rule-form" onSubmit={handleAddAlertRule}>
                <h3 className="settings-subtitle">Add a rule</h3>
                <label>
                  <span>Scenario</span>
                  <select value={newRuleScenario} onChange={(e) => setNewRuleScenario(e.target.value as AlertScenario)}>
                    <option value="pu_near">Near pickup</option>
                    <option value="del_near">Near delivery</option>
                  </select>
                </label>
                <label>
                  <span>Distance (miles)</span>
                  <input
                    type="number"
                    min="0.1"
                    max="500"
                    step="0.5"
                    value={newRuleDistance}
                    onChange={(e) => setNewRuleDistance(e.target.value)}
                    required
                  />
                </label>
                <label>
                  <span>Custom message (optional)</span>
                  <textarea
                    value={newRuleMessage}
                    onChange={(e) => setNewRuleMessage(e.target.value)}
                    placeholder="Use {miles} and {load_id} - leave blank for the standard message"
                    rows={2}
                  />
                </label>
                {alertRuleError && <p className="form-error">{alertRuleError}</p>}
                <button className="btn btn-primary" type="submit" disabled={alertRuleBusy}>
                  {alertRuleBusy ? 'Adding...' : 'Add rule'}
                </button>
              </form>
            </div>
          </section>
        )}

        {/* ---------------- Fleet: trucks and trailers ---------------- */}
        <section className={sectionClass('fleet')}>
          <h2 className="section-title">Trucks</h2>
          <div className="card">
            {trucks.length > 0 ? (
              <div className="dispatcher-list">
                {trucks.map((t) => (
                  <div key={t.id} className="dispatcher-row">
                    <span className="unit-chip">{t.unit_number}</span>
                    <span className="dispatcher-username">
                      {t.driver ? (t.driver.full_name || t.driver.driver_bot_id) : (
                        <span className="text-warn">No driver</span>
                      )}
                    </span>

                    {/* Assignment happens inline. Hooking a trailer or moving
                        a driver is something dispatch does several times a
                        day, so it shouldn't cost a modal each time. */}
                    <select
                      className="unit-select"
                      aria-label={`Trailer for truck ${t.unit_number}`}
                      value={t.trailer?.id ?? ''}
                      disabled={fleetBusy}
                      onChange={(e) =>
                        runFleetAction(
                          () => dashboardApi.assignTruck(t.id, {
                            trailer_id: e.target.value ? Number(e.target.value) : null,
                          }),
                          "Couldn't change the trailer.",
                        )
                      }
                    >
                      <option value="">No trailer</option>
                      {trailers
                        // A trailer already on another truck isn't available,
                        // but this truck's own stays listed so it can show as
                        // the current selection.
                        .filter((tr) => !tr.in_use || tr.id === t.trailer?.id)
                        .map((tr) => (
                          <option key={tr.id} value={tr.id}>{tr.unit_number}</option>
                        ))}
                    </select>

                    <select
                      className="unit-select"
                      aria-label={`Driver for truck ${t.unit_number}`}
                      value={t.driver?.id ?? ''}
                      disabled={fleetBusy}
                      onChange={(e) =>
                        runFleetAction(
                          () => dashboardApi.assignTruck(t.id, {
                            driver_id: e.target.value ? Number(e.target.value) : null,
                          }),
                          "Couldn't change the driver.",
                        )
                      }
                    >
                      <option value="">No driver</option>
                      {drivers.map((d) => (
                        <option key={d.id} value={d.id}>{d.full_name || d.driver_bot_id}</option>
                      ))}
                    </select>

                    <button
                      className="btn btn-danger-ghost btn-sm"
                      onClick={() => handleDeleteTruck(t)}
                      disabled={fleetBusy}
                    >
                      Delete
                    </button>
                  </div>
                ))}
              </div>
            ) : (
              <p className="empty">No trucks yet. Add your first unit below.</p>
            )}
          </div>

          <div className="card" style={{ marginTop: 12 }}>
            <h3 className="settings-subtitle">Add a truck</h3>
            <form className="form form-inline" onSubmit={handleAddTruck}>
              <input
                type="text"
                value={newTruckUnit}
                onChange={(e) => setNewTruckUnit(e.target.value)}
                placeholder="Unit number, e.g. 1001"
                maxLength={30}
                required
              />
              <button className="btn btn-primary" type="submit" disabled={fleetBusy}>
                {fleetBusy ? 'Saving...' : 'Add truck'}
              </button>
            </form>
          </div>

          <h2 className="section-title" style={{ marginTop: 32 }}>Trailers</h2>
          <div className="card">
            {trailers.length > 0 ? (
              <div className="dispatcher-list">
                {trailers.map((tr) => (
                  <div key={tr.id} className="dispatcher-row">
                    <span className="unit-chip">{tr.unit_number}</span>
                    <span className="dispatcher-username">
                      {tr.in_use ? 'Hooked to a truck' : <span className="settings-row-hint">Available</span>}
                    </span>
                    <button
                      className="btn btn-danger-ghost btn-sm"
                      onClick={() => handleDeleteTrailer(tr)}
                      disabled={fleetBusy}
                    >
                      Delete
                    </button>
                  </div>
                ))}
              </div>
            ) : (
              <p className="empty">No trailers yet.</p>
            )}
          </div>

          <div className="card" style={{ marginTop: 12 }}>
            <h3 className="settings-subtitle">Add a trailer</h3>
            <form className="form form-inline" onSubmit={handleAddTrailer}>
              <input
                type="text"
                value={newTrailerUnit}
                onChange={(e) => setNewTrailerUnit(e.target.value)}
                placeholder="Unit number, e.g. 373783"
                maxLength={30}
                required
              />
              <button className="btn btn-primary" type="submit" disabled={fleetBusy}>
                {fleetBusy ? 'Saving...' : 'Add trailer'}
              </button>
            </form>
          </div>

          {fleetError && <Alert kind="error" onDismiss={() => setFleetError('')}>{fleetError}</Alert>}
        </section>

        {/* ---------------- Notifications ---------------- */}
        <section className={sectionClass('notifications')}>
          <h2 className="section-title">Notifications</h2>
          <div className="card">
            <NotificationSettings />
          </div>
        </section>

        {/* ---------------- Drivers ---------------- */}
        <section className={sectionClass('drivers')}>
            <h2 className="section-title">Drivers</h2>

            <GroupProfileReview proposals={groupProfiles} onResolved={handleGroupProfileResolved} />

            <div className="card">
              {drivers.length > 0 ? (
                <div className="dispatcher-list">
                  {drivers.map((d) => (
                    <div key={d.id}>
                      <div className="dispatcher-row">
                        <span className={`status-dot ${d.telegram_group_id ? 'on' : 'off'}`} />
                        <span className="dispatcher-username">{d.full_name}</span>
                        <span className="dispatcher-role mono">#{d.driver_bot_id}</span>
                        <span className={`status-badge ${d.telegram_group_id ? 'is-connected' : 'is-disconnected'}`}>
                          {d.telegram_group_id ? d.telegram_group_title || 'Linked' : 'Not linked yet'}
                        </span>
                        {!d.telegram_group_id && (
                          <button
                            className="btn btn-ghost btn-sm"
                            onClick={() => handleShowLinkCode(d.id)}
                            disabled={linkBusy}
                          >
                            {linkDriverId === d.id && linkCode ? 'New code' : 'Get linking code'}
                          </button>
                        )}
                        <button
                          className="btn btn-ghost btn-sm"
                          onClick={() => openDriverGroup(d)}
                        >
                          {groupDriverId === d.id ? 'Close' : 'Group'}
                        </button>
                        <button
                          className="btn btn-ghost btn-sm"
                          onClick={() => openDriverDetails(d)}
                        >
                          {detailsDriverId === d.id ? 'Close' : 'Details'}
                        </button>
                        <button
                          className="btn btn-danger-ghost btn-sm"
                          onClick={() => handleDeleteDriver(d)}
                          disabled={fleetBusy}
                        >
                          Remove
                        </button>
                      </div>
                      {groupDriverId === d.id && (
                        <div className="twofa-enroll">
                          <p className="method-hint">
                            Which Telegram group {d.full_name || d.driver_bot_id}'s loads are
                            posted to. Only groups this company has already linked can be chosen
                            here - to use a new one, add the bot to it and run the linking code
                            inside it, which is what proves you are in that group.
                          </p>
                          {d.telegram_group_id ? (
                            <p className="settings-hint">
                              Currently: <strong>{d.telegram_group_title || 'Linked group'}</strong>
                            </p>
                          ) : (
                            <p className="settings-hint">Not linked to a group yet.</p>
                          )}
                          {groupError && <ErrorMessage className="form-error" text={groupError} />}
                          <div className="settings-row" style={{ marginTop: 12, gap: 8 }}>
                            <select
                              className="input"
                              value={d.telegram_group_id ?? ''}
                              disabled={groupBusy}
                              onChange={(e) =>
                                applyDriverGroup(d.id, e.target.value ? Number(e.target.value) : null)
                              }
                            >
                              <option value="">Not linked</option>
                              {companyGroups.map((g) => (
                                <option key={g.telegram_group_id} value={g.telegram_group_id}>
                                  {g.telegram_group_title || `Group ${g.telegram_group_id}`}
                                  {g.driver_id !== d.id &&
                                    ` - currently ${g.full_name || g.driver_bot_id}'s`}
                                </option>
                              ))}
                            </select>
                          </div>
                          {companyGroups.some((g) => g.driver_id !== d.id) && (
                            <p className="settings-hint" style={{ marginTop: 8 }}>
                              Choosing a group that belongs to another driver moves it: they are
                              left unlinked, and their loads stop going there.
                            </p>
                          )}
                        </div>
                      )}
                      {detailsDriverId === d.id && (
                        <div className="twofa-enroll">
                          <p className="method-hint">
                            Truck and driver details. The bot fills these in from the group's
                            description when there is one - this is for typing them in yourself,
                            or fixing one afterwards.
                          </p>
                          <FieldGrid
                            values={detailsValues}
                            disabled={detailsBusy}
                            onChange={(field, value) =>
                              setDetailsValues((prev) => ({ ...prev, [field]: value }))
                            }
                          />
                          {detailsError && <ErrorMessage className="form-error" text={detailsError} />}
                          <button
                            className="btn btn-primary btn-sm"
                            style={{ marginTop: 12 }}
                            onClick={() => handleSaveDriverDetails(d.id)}
                            disabled={detailsBusy}
                          >
                            {detailsBusy ? 'Saving...' : 'Save details'}
                          </button>
                        </div>
                      )}
                      {linkDriverId === d.id && linkCode && (
                        <div className="twofa-enroll">
                          <p className="method-hint">
                            Add the Unector bot to {d.full_name}'s Telegram group, then send in that
                            group: <code className="mono">{linkCode.bot_command}</code>
                          </p>
                          <button
                            className="btn btn-primary btn-sm"
                            onClick={() => handleCheckDriverLinked(d.id)}
                            disabled={linkBusy}
                          >
                            {linkBusy ? 'Checking...' : "I've sent it - check now"}
                          </button>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              ) : (
                <p className="empty">No drivers yet - add one below.</p>
              )}
            </div>

            <div className="card" style={{ marginTop: 12 }}>
              <h3 className="settings-subtitle">Add a driver</h3>
              {billing && billing.active_drivers >= billing.max_drivers && (
                <p className="settings-hint">
                  You're at your plan's driver limit ({billing.active_drivers}/{billing.max_drivers}).{' '}
                  <Link to="/pages/pricing">Upgrade your plan</Link> to add more.
                </p>
              )}
              <form className="form" onSubmit={handleAddDriver}>
                <label>
                  <span>Driver name</span>
                  <input
                    type="text"
                    value={newDriverName}
                    onChange={(e) => setNewDriverName(e.target.value)}
                    placeholder="Full name"
                    maxLength={150}
                    required
                  />
                </label>
                {addDriverError && <ErrorMessage className="form-error" text={addDriverError} />}
                <button className="btn btn-primary" type="submit" disabled={addDriverBusy}>
                  {addDriverBusy ? 'Adding...' : 'Add driver'}
                </button>
              </form>
            </div>
          </section>

        {/* ---------------- Dispatchers ---------------- */}
        {isOwner && (
          <section className={sectionClass('dispatchers')}>
            <h2 className="section-title">Dispatchers</h2>

            <div className="card">
              {dispatchers.length > 0 ? (
                <div className="dispatcher-list">
                  {dispatchers.map((d) => (
                    <div key={d.id} className="dispatcher-row">
                      <span className="team-avatar">
                        {d.avatar ? <img src={d.avatar} alt="" /> : d.username.slice(0, 2).toUpperCase()}
                      </span>
                      <span className="dispatcher-username">{d.username}</span>
                      <span className="dispatcher-role mono">{d.role}</span>
                      <button className="btn btn-ghost btn-sm" onClick={() => openEditDispatcher(d)}>
                        Edit
                      </button>
                      <button className="btn btn-danger-ghost btn-sm" onClick={() => handleDeleteDispatcher(d)}>
                        Remove
                      </button>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="empty">No dispatcher logins yet.</p>
              )}
            </div>

            <div className="card" style={{ marginTop: 12 }}>
              <h3 className="settings-subtitle">Add a dispatcher</h3>
              {billing && billing.max_dispatchers !== null &&
                billing.dispatchers >= billing.max_dispatchers && (
                <p className="settings-hint">
                  You&apos;re at your plan&apos;s dispatcher limit ({billing.dispatchers}/
                  {billing.max_dispatchers}). <Link to="/pages/pricing">Upgrade your plan</Link> to
                  add more. Nobody loses a login they already have.
                </p>
              )}
              <form className="form" onSubmit={handleAddDispatcher}>
                <label>
                  <span>Username</span>
                  <input
                    type="text"
                    value={newUsername}
                    onChange={(e) => setNewUsername(e.target.value)}
                    placeholder="new dispatcher username"
                    required
                  />
                </label>
                <label>
                  <span>Password</span>
                  <PasswordInput
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    placeholder="min. 6 characters"
                    minLength={6}
                    required
                  />
                </label>
                {addDispatcherError && <p className="form-error">{addDispatcherError}</p>}
                <button className="btn btn-primary" type="submit" disabled={addDispatcherBusy}>
                  {addDispatcherBusy ? 'Creating...' : 'Create dispatcher login'}
                </button>
              </form>
            </div>
          </section>
        )}

        {/* ---------------- Team - read-only roster, available to owner and dispatcher ---------------- */}
        <section className={sectionClass('team')}>
          <h2 className="section-title">Team</h2>
          <div className="card">
            {team.length > 0 ? (
              <div className="dispatcher-list">
                {team.map((member) => (
                  <div key={`${member.role}-${member.name}`} className="dispatcher-row">
                    <span className="team-avatar">
                      {member.avatar ? <img src={member.avatar} alt="" /> : member.name.slice(0, 2).toUpperCase()}
                    </span>
                    <span className="dispatcher-username">{member.name}</span>
                    <span className="dispatcher-role mono">{member.role}</span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="empty">No teammates yet.</p>
            )}
          </div>
        </section>

        {/* ---------------- Security (2FA) - available to owner and dispatcher ---------------- */}
        <section className={sectionClass('security')}>
          <h2 className="section-title">Security</h2>
          <TwoFactorSettings />
        </section>
      </div>

      {/* ---------------- Samsara connect modal ---------------- */}
      <AnimatePresence>
        {samsaraModalOpen && (
          <motion.div
            className="modal-overlay"
            onClick={() => setSamsaraModalOpen(false)}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
          >
            <motion.div
              className="modal-card"
              onClick={(e) => e.stopPropagation()}
              initial={{ opacity: 0, scale: 0.95, y: 12 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: 12 }}
              transition={{ duration: 0.2, ease: 'easeOut' }}
            >
              <h3>Connect Samsara</h3>
              <p className="modal-hint">
                In your Samsara dashboard: Settings (gear icon) → Developer → API Tokens → Add an API Token.
                Tag Access: Entire Organization. Permission Scope: <strong>Read Vehicle Statistics</strong> under Vehicles.
                Paste the token below.
              </p>
              <label>
                <span>Samsara API token</span>
                <PasswordInput
                  value={samsaraKey}
                  onChange={(e) => setSamsaraKey(e.target.value)}
                  placeholder="samsara_api_..."
                  autoFocus
                />
              </label>
              {samsaraError && <p className="form-error">{samsaraError}</p>}
              <div className="modal-actions">
                <button className="btn btn-ghost" onClick={() => setSamsaraModalOpen(false)}>
                  Cancel
                </button>
                <button className="btn btn-primary" onClick={handleConnectSamsara} disabled={samsaraBusy || !samsaraKey.trim()}>
                  {samsaraBusy ? 'Connecting...' : 'Connect'}
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {editDispatcher && (
          <motion.div
            className="modal-overlay"
            onClick={() => setEditDispatcher(null)}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
          >
            <motion.div
              className="modal-card"
              onClick={(e) => e.stopPropagation()}
              initial={{ opacity: 0, scale: 0.95, y: 12 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: 12 }}
              transition={{ duration: 0.2, ease: 'easeOut' }}
            >
              <h3>Edit Dispatcher</h3>
              <form className="form" onSubmit={handleSaveDispatcherEdit}>
                <label>
                  <span>Username</span>
                  <input
                    type="text"
                    value={editUsername}
                    onChange={(e) => setEditUsername(e.target.value)}
                    autoFocus
                    required
                  />
                </label>
                <label>
                  <span>New password (optional)</span>
                  <PasswordInput
                    value={editPassword}
                    onChange={(e) => setEditPassword(e.target.value)}
                    placeholder="Leave blank to keep current password"
                    minLength={6}
                  />
                </label>
                {editDispatcherError && <p className="form-error">{editDispatcherError}</p>}
                <div className="modal-actions">
                  <button type="button" className="btn btn-ghost" onClick={() => setEditDispatcher(null)}>
                    Cancel
                  </button>
                  <button type="submit" className="btn btn-primary" disabled={editDispatcherBusy}>
                    {editDispatcherBusy ? 'Saving...' : 'Save changes'}
                  </button>
                </div>
              </form>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
    </Layout>
  )
}
