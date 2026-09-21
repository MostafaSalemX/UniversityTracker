import { defineRailway, github, preserve, project, service, volume } from "railway/iac";

// Railway infrastructure for the Moodle checker.
// Apply with: railway config plan && railway config apply
// Secrets are preserve()d: their values live only in Railway, never in this file.

export default defineRailway(() => {
  const state = volume("universitytracker-volume", {
    region: "ams",
    sizeMB: 5000,
    allowOnlineResize: true,
    alerts: { usage: { "80": {}, "95": {}, "100": {} } },
  });

  const checker = service("UniversityTracker", {
    source: github("MostafaSalemX/UniversityTracker", { branch: "main", checkSuites: false }),
    build: { builder: "DOCKERFILE", dockerfilePath: "Dockerfile" },
    deploy: {
      // 07:00 / 13:00 / 20:00 Africa/Cairo while on summer time (UTC+3).
      cronSchedule: "0 4,10,17 * * *",
      // A cron job must exit; never restart it.
      restartPolicyType: "NEVER",
    },
    replicas: { ams: 1 },
    networking: { privateNetworkEndpoint: "universitytracker" },
    volumeMounts: { "/data": state },
    env: {
      MOODLE_URL: preserve(),
      MOODLE_USERNAME: preserve(),
      MOODLE_PASSWORD: preserve(),
      TELEGRAM_BOT_TOKEN: preserve(),
      TELEGRAM_CHAT_ID: preserve(),
      STATE_PATH: "/data/state.json",
      TZ_NAME: "Africa/Cairo",
    },
  });

  return project("Univerity Tracker", {
    resources: [checker, state],
  });
});
