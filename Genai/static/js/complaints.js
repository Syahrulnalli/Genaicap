(() => {
  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || '';
  const selector = document.getElementById('status-select');
  if (selector) {
    let savedStatus = selector.value;
    selector.addEventListener('change', async () => {
      const feedback = document.getElementById('status-feedback');
      selector.disabled = true;
      feedback.textContent = 'Saving...';
      try {
        const response = await fetch(`/api/complaints/${selector.dataset.complaintId}/status`, {
          method: 'POST',
          headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrfToken},
          body: JSON.stringify({status: selector.value})
        });
        const result = await response.json();
        if (!response.ok || !result.success) throw new Error(result.error || 'Could not save status.');
        savedStatus = result.data.status;
        feedback.textContent = 'Status saved.';
        window.showToast('Status updated.');
      } catch (error) {
        selector.value = savedStatus;
        feedback.textContent = error.message;
        window.showToast(error.message, 'error');
      } finally {
        selector.disabled = false;
      }
    });
  }

  const priority = document.getElementById('priority-select');
  if (priority) {
    let savedPriority = priority.value;
    priority.addEventListener('change', async () => {
      const feedback = document.getElementById('priority-feedback');
      priority.disabled = true;
      feedback.textContent = 'Saving...';
      try {
        const response = await fetch(`/api/complaints/${priority.dataset.complaintId}/priority`, {
          method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrfToken},
          body: JSON.stringify({priority: priority.value})
        });
        const result = await response.json();
        if (!response.ok || !result.success) throw new Error(result.error || 'Could not save priority.');
        savedPriority = result.data.priority;
        feedback.textContent = 'Priority saved.';
        window.showToast('Priority updated.');
      } catch (error) {
        priority.value = savedPriority;
        feedback.textContent = error.message;
        window.showToast(error.message, 'error');
      } finally {
        priority.disabled = false;
      }
    });
  }

  const retry = document.getElementById('retry-analysis');
  if (retry) retry.addEventListener('click', async () => {
    retry.disabled = true;
    retry.querySelector('.button-label').textContent = 'Analyzing...';
    retry.querySelector('.button-loader').classList.remove('hidden');
    try {
      const response = await fetch(`/api/complaints/${retry.dataset.complaintId}/analyze`, {method: 'POST', headers: {'X-CSRFToken': csrfToken}});
      const result = await response.json();
      if (!response.ok || !result.success) throw new Error(result.error || 'Analysis could not be completed.');
      window.location.reload();
    } catch (error) {
      window.showToast(error.message, 'error');
      retry.disabled = false;
      retry.querySelector('.button-label').textContent = 'Retry analysis';
      retry.querySelector('.button-loader').classList.add('hidden');
    }
  });
})();
