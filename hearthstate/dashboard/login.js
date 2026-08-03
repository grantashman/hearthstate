const feedback = document.querySelector('#loginFeedback');

document.querySelectorAll('[data-user]').forEach((button) => {
  button.addEventListener('click', async () => {
    document.querySelectorAll('[data-user]').forEach((choice) => { choice.disabled = true; });
    feedback.classList.add('is-hidden');
    try {
      const response = await fetch('/api/session', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user: button.dataset.user }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || 'Could not start Hearthstate session');
      window.location.assign('/');
    } catch (error) {
      feedback.textContent = error.message;
      feedback.classList.remove('is-hidden');
      document.querySelectorAll('[data-user]').forEach((choice) => { choice.disabled = false; });
    }
  });
});
