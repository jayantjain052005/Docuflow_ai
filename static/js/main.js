/**
 * DocuFlow AI — Main JavaScript
 * Small utilities for UX enhancements.
 */

// Auto-dismiss flash messages after 5 seconds
document.addEventListener("DOMContentLoaded", () => {
  const flashes = document.querySelectorAll(".flash-msg");
  flashes.forEach((el) => {
    setTimeout(() => {
      el.style.transition = "opacity 0.4s";
      el.style.opacity = "0";
      setTimeout(() => el.remove(), 400);
    }, 5000);
  });
});
