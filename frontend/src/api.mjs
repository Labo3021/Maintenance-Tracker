// Proposed contract only: coordinate these fields with the backend owner.
// API keys belong on the backend; VITE_ values are public browser configuration.
export async function askAssistant(baseUrl, equipmentId, message, {signal, request = fetch} = {}) {
  if (!baseUrl) throw new Error('The AI assistant is not connected yet.');
  const response = await request(`${baseUrl.replace(/\/+$/, '')}/assistant`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({equipment_id: equipmentId, message}),
    signal
  });
  if (!response.ok) throw new Error(`The assistant could not respond (${response.status}). Please try again.`);
  const result = await response.json();
  if (!result || typeof result.answer !== 'string' || !result.answer.trim()) {
    throw new Error('The assistant returned an unexpected response.');
  }
  return result.answer;
}
