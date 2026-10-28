(() => {
  const form = document.getElementById('complaint-form');
  if (!form) return;
  const textarea = form.elements.complaint_text;
  const count = document.getElementById('char-count');
  const alert = document.getElementById('form-error');
  const button = form.querySelector('[type="submit"]');
  const customerMode = form.dataset.customerMode === 'true';
  const idleButtonLabel = customerMode ? 'Submit complaint' : 'Analyze complaint';
  textarea.addEventListener('input', () => count.textContent = textarea.value.length);
  const clearErrors = () => { form.querySelectorAll('.field-error').forEach(e => e.textContent = ''); form.querySelectorAll('.field.invalid').forEach(e => e.classList.remove('invalid')); };
  form.addEventListener('submit', async event => {
    event.preventDefault(); clearErrors(); alert.classList.add('hidden');
    const body = Object.fromEntries(new FormData(form).entries());
    const errors = {};
    if (form.elements.customer_name && !body.customer_name.trim()) errors.customer_name = 'Enter your name.';
    if (form.elements.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(body.email.trim())) errors.email = 'Enter a valid email address.';
    if (body.complaint_text.trim().length < 15 || body.complaint_text.trim().length > 5000) errors.complaint_text = 'Use 15 to 5,000 characters to describe the issue.';
    Object.entries(errors).forEach(([name, message]) => { const input = form.elements[name]; input.closest('.field').classList.add('invalid'); input.closest('.field').querySelector('.field-error').textContent = message; });
    if (Object.keys(errors).length) { alert.textContent = 'Please check the highlighted fields.'; alert.classList.remove('hidden'); return; }
    button.disabled = true; button.querySelector('.button-label').textContent = customerMode ? 'Submitting...' : 'Analyzing...'; button.querySelector('.button-loader').classList.remove('hidden');
    try {
      const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || '';
      const response = await fetch('/api/complaints', { method: 'POST', headers: {'Content-Type':'application/json', 'X-CSRFToken':csrfToken}, body: JSON.stringify(body) });
      const result = await response.json();
      if (!response.ok || !result.success) {
        if (result.errors) Object.entries(result.errors).forEach(([name, message]) => { const input = form.elements[name]; if (input) { input.closest('.field').classList.add('invalid'); input.closest('.field').querySelector('.field-error').textContent = message; } });
        throw new Error(result.error || 'We could not submit your complaint.');
      }
      window.location.href = result.data.url;
    } catch (error) {
      alert.textContent = error.message || 'Network error. Please try again.'; alert.classList.remove('hidden');
      button.disabled = false; button.querySelector('.button-label').textContent = idleButtonLabel; button.querySelector('.button-loader').classList.add('hidden');
    }
  });
})();
