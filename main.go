package main

import (
	"log/slog"
	"os"
	"strings"

	"github.com/komari-monitor/komari/cmd"
	"github.com/komari-monitor/komari/utils"
	logger "github.com/komari-monitor/komari/utils/log"
)

func resolveLogLevel() slog.Level {
	keys := []string{"KOMARI_LOG_LEVEL", "LOG_LEVEL", "log-level"}
	for _, key := range keys {
		value := strings.TrimSpace(os.Getenv(key))
		if value == "" {
			continue
		}
		switch strings.ToLower(value) {
		case "debug":
			return slog.LevelDebug
		case "info":
			return slog.LevelInfo
		case "warn", "warning":
			return slog.LevelWarn
		case "error":
			return slog.LevelError
		default:
			return slog.LevelWarn
		}
	}
	return slog.LevelWarn
}

func main() {
	logger.Setup(resolveLogLevel())

	logger.Infof("server", "Komari Monitor %s (hash: %s)", utils.CurrentVersion, utils.VersionHash)

	cmd.Execute()
}
