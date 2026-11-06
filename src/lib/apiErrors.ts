// Demo + sähköposti -ketjun virheviestit. 409 voi tarkoittaa joko do not contact -merkintää
// tai julkaisematonta demoa, joten viesti valitaan backendin detail-tekstin perusteella.

export async function readDetail(res: Response): Promise<string> {
  try {
    const data: unknown = await res.json();
    if (data && typeof data === 'object' && 'detail' in data && typeof data.detail === 'string') {
      return data.detail;
    }
  } catch {
    // ei JSON-runkoa
  }
  return '';
}

export function outreachErrorMessage(status: number, detail: string): string {
  const d = detail.toLowerCase();
  if (status === 409 && d.includes('do not contact')) {
    return 'This lead is marked do not contact. Demo, publishing and email are blocked.';
  }
  if (status === 409 && d.includes('not published')) {
    return 'The demo is not published, so no email was created. Publish the demo first.';
  }
  if (status === 428) return 'Add your sender profile in Settings (sidebar) before creating demos and emails.';
  if (status === 503) return 'Publishing is not configured (R2_* and DEMO_PUBLIC_BASE_URL in backend .env). No email was created.';
  if (status === 502 && (d.includes('upload') || d.includes('r2'))) {
    return 'Publishing failed: the demo could not be uploaded. No email was created. Try again.';
  }
  if (status === 502 && d.includes('validation')) {
    return 'The AI content did not pass validation twice. Try generating again.';
  }
  if (status === 502) return 'The server could not complete the request. Try again.';
  if (status === 500) return 'Server error. Check OPENAI_API_KEY in backend .env.';
  return `Server error: ${status}`;
}
