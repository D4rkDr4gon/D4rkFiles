window {
  background-color: #000000;
}

/* ── Banner ASCII (centro) — color = primary del tema, lo escribe theme-switch.sh ── */
@define-color banner_color @primary@;

#banner-label {
  font-family: "@font_mono_alt@";
  font-size: 18px;
  color: @banner_color;
}

#window-box {
  background: transparent;
}

/* ── Clock (bottom-left) ── */
#clock-label {
  font-family: "@font_mono_alt@";
  font-size: 80px;
  font-weight: bold;
  color: #e0e0e0;
  text-shadow: 0 2px 8px rgba(0, 0, 0, 0.7);
}

#date-label {
  font-family: "@font_mono_alt@";
  font-size: 22px;
  color: #b0b0b0;
  text-shadow: 0 2px 6px rgba(0, 0, 0, 0.6);
}

/* ── Auth form (bottom-right) ── */
#body-revealer {
  background: rgba(0, 0, 0, 0.45);
  border-radius: @radius_outer@px;
  padding: 20px 24px;
  min-width: 320px;
}

#input-label {
  font-family: "@font_mono_alt@";
  font-size: 15px;
  color: #c0c0c0;
}

#input-field {
  font-family: "@font_mono_alt@";
  font-size: 16px;
  background: rgba(255, 255, 255, 0.08);
  color: #ffffff;
  border: 1px solid rgba(255, 255, 255, 0.15);
  border-radius: @radius@px;
  padding: 8px 12px;
  caret-color: #bbbbbb;
}

#input-field:focus {
  border-color: rgba(255, 255, 255, 0.4);
  background: rgba(255, 255, 255, 0.12);
}

#error-label {
  font-family: "@font_mono_alt@";
  font-size: 13px;
  color: #ff6b6b;
}

#warning-label {
  font-family: "@font_mono_alt@";
  font-size: 13px;
  color: #ffd93d;
}

#unlock-button {
  font-family: "@font_mono_alt@";
  font-size: 14px;
  background: rgba(255, 255, 255, 0.12);
  color: #e0e0e0;
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: @radius@px;
  padding: 6px 18px;
}

#unlock-button:hover {
  background: rgba(255, 255, 255, 0.22);
}

/* ── Messages ── */
#message-box {
  background: transparent;
}

/* ── Playerctl module ── */
@define-color accent #bbbbbb;

playerctl-label {
  font-family: "@font_mono_alt@";
  font-size: 14px;
  color: #aaaaaa;
}

/* ── Userinfo module ── */
userinfo-label {
  font-family: "@font_mono_alt@";
  font-size: 15px;
  color: #c0c0c0;
}

userinfo-avatar {
  border-radius: 50%;
}
