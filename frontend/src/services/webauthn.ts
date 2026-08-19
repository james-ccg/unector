// Thin wrapper around the browser's native WebAuthn API (navigator.credentials).
// No extra npm package needed - every modern browser ships this natively.

function base64urlToBuffer(value: string): ArrayBuffer {
  const padded = value.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - (value.length % 4)) % 4)
  const raw = atob(padded)
  const buffer = new ArrayBuffer(raw.length)
  const view = new Uint8Array(buffer)
  for (let i = 0; i < raw.length; i++) view[i] = raw.charCodeAt(i)
  return buffer
}

function bufferToBase64url(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer)
  let binary = ''
  for (const byte of bytes) binary += String.fromCharCode(byte)
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

export function isWebAuthnSupported(): boolean {
  return typeof window !== 'undefined' && !!window.PublicKeyCredential
}

/** Runs the browser's "create a new security key" flow and returns a JSON
 * string ready to POST straight back to the backend for verification. */
export async function createCredential(optionsJson: string): Promise<string> {
  const options = JSON.parse(optionsJson)

  const publicKey: CredentialCreationOptions['publicKey'] = {
    ...options,
    challenge: base64urlToBuffer(options.challenge),
    user: { ...options.user, id: base64urlToBuffer(options.user.id) },
    excludeCredentials: (options.excludeCredentials || []).map((c: any) => ({
      ...c,
      id: base64urlToBuffer(c.id),
    })),
  }

  const credential = (await navigator.credentials.create({ publicKey })) as PublicKeyCredential
  const response = credential.response as AuthenticatorAttestationResponse

  return JSON.stringify({
    id: credential.id,
    rawId: bufferToBase64url(credential.rawId),
    type: credential.type,
    response: {
      clientDataJSON: bufferToBase64url(response.clientDataJSON),
      attestationObject: bufferToBase64url(response.attestationObject),
    },
  })
}

/** Runs the browser's "use a security key to sign in" flow. */
export async function getCredential(optionsJson: string): Promise<string> {
  const options = JSON.parse(optionsJson)

  const publicKey: CredentialRequestOptions['publicKey'] = {
    ...options,
    challenge: base64urlToBuffer(options.challenge),
    allowCredentials: (options.allowCredentials || []).map((c: any) => ({
      ...c,
      id: base64urlToBuffer(c.id),
    })),
  }

  const credential = (await navigator.credentials.get({ publicKey })) as PublicKeyCredential
  const response = credential.response as AuthenticatorAssertionResponse

  return JSON.stringify({
    id: credential.id,
    rawId: bufferToBase64url(credential.rawId),
    type: credential.type,
    response: {
      clientDataJSON: bufferToBase64url(response.clientDataJSON),
      authenticatorData: bufferToBase64url(response.authenticatorData),
      signature: bufferToBase64url(response.signature),
      userHandle: response.userHandle ? bufferToBase64url(response.userHandle) : null,
    },
  })
}
