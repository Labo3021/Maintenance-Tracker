// Proposed contract only: coordinate these fields with the backend owner.
// API keys belong on the backend; VITE_ values are public browser configuration.
export async function askAssistant(baseUrl, equipmentId, message, {image, signal, request = fetch} = {}) {
  if (!baseUrl) throw new Error('The AI assistant is not connected yet.');
  // Text keeps the existing JSON contract. A photo uses multipart/form-data;
  // the backend owner must support the optional image field before enabling it.
  const body = image ? new FormData() : JSON.stringify({equipment_id: equipmentId, message});
  if (image) {
    body.append('equipment_id', equipmentId);
    body.append('message', message);
    body.append('image', image, image.name);
  }
  const response = await request(`${baseUrl.replace(/\/+$/, '')}/assistant`, {
    method: 'POST',
    ...(image ? {} : {headers: {'Content-Type': 'application/json'}}),
    body,
    signal
  });
  if (!response.ok) throw new Error(`The assistant could not respond (${response.status}). Please try again.`);
  const result = await response.json();
  if (!result || typeof result.answer !== 'string' || !result.answer.trim()) {
    throw new Error('The assistant returned an unexpected response.');
  }
  return result.answer;
}
