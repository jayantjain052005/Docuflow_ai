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

  const menuButton = document.querySelector(".mobile-menu-toggle");
  const menuPanel = document.getElementById("primaryNavigation");

  if (menuButton && menuPanel) {
    menuButton.addEventListener("click", () => {
      const isOpen = menuPanel.classList.toggle("is-open");
      menuButton.setAttribute("aria-expanded", String(isOpen));
      menuButton.setAttribute("aria-label", isOpen ? "Close navigation" : "Open navigation");
      const icon = menuButton.querySelector(".bi");
      if (icon) {
        icon.classList.toggle("bi-list", !isOpen);
        icon.classList.toggle("bi-x-lg", isOpen);
      }
    });

    menuPanel.querySelectorAll("a").forEach((link) => {
      link.addEventListener("click", () => {
        menuPanel.classList.remove("is-open");
        menuButton.setAttribute("aria-expanded", "false");
        menuButton.setAttribute("aria-label", "Open navigation");
        const icon = menuButton.querySelector(".bi");
        if (icon) {
          icon.classList.add("bi-list");
          icon.classList.remove("bi-x-lg");
        }
      });
    });
  }
});
