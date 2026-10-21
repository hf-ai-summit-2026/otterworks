module Api
  module V1
    module Admin
      # Receives Grafana Unified Alerting webhook payloads and converts them
      # into Incident records with an auto-triggered Devin session.
      #
      # Grafana POST body shape:
      #   {
      #     "receiver": "otterworks-webhook",
      #     "status": "firing" | "resolved",
      #     "alerts": [
      #       {
      #         "status": "firing" | "resolved",
      #         "labels": { "alertname": "...", "severity": "...", "affected_service": "..." },
      #         "annotations": { "summary": "...", "description": "..." },
      #         "startsAt": "2024-01-01T00:00:00Z"
      #       }
      #     ]
      #   }
      class AlertsController < ApplicationController
        before_action :verify_alert_secret

        SEVERITY_MAP = {
          'critical' => 'critical',
          'high' => 'high',
          'warning' => 'medium',
          'info' => 'low'
        }.freeze

        # POST /api/v1/admin/alerts/ingest
        def ingest
          alerts = params[:alerts]
          return render json: { error: 'Missing alerts array' }, status: :bad_request unless alerts.is_a?(Array)

          processed = alerts.map { |alert| process_alert(alert) }.compact

          render json: { received: alerts.size, processed: processed.size, incidents: processed }
        end

        private

        def process_alert(alert)
          labels           = alert[:labels] || {}
          alert_name       = labels[:alertname].to_s
          affected_service = labels[:affected_service].to_s.presence || labels[:service].to_s.presence

          case alert[:status].to_s
          when 'resolved'
            resolve_incident(affected_service, alert_name)
            nil
          when 'firing'
            open_incident(alert, alert_name, affected_service) if affected_service.present?
          end
        rescue ActiveRecord::RecordInvalid => e
          Rails.logger.error("Failed to create incident from alert #{alert_name}: #{e.message}")
          nil
        end

        def open_incident(alert, alert_name, affected_service)
          # Deduplicate: skip if an active incident for this service already exists
          existing = active_incident_for(affected_service)
          if existing
            Rails.logger.info("Alert #{alert_name} skipped — incident #{existing.id} already open for " \
                              "#{affected_service}")
            return { skipped: true, incident_id: existing.id, reason: 'duplicate' }
          end

          auto_investigate = AdminSettingsService.auto_investigate_enabled?
          incident = Incident.create!(
            incident_attributes(alert, alert_name, affected_service, auto_investigate)
          )
          session_result = start_devin_session(incident, auto_investigate)

          Rails.logger.info("Incident #{incident.id} created from alert #{alert_name}, " \
                            "devin=#{session_result.present?}")

          { incident_id: incident.id, alert: alert_name, devin_session: session_result.present? }
        end

        def incident_attributes(alert, alert_name, affected_service, auto_investigate)
          labels      = alert[:labels] || {}
          annotations = alert[:annotations] || {}
          summary     = annotations[:summary].to_s
          description = annotations[:description].to_s.presence || summary

          {
            title: summary.presence || "#{alert_name}: #{affected_service} alert firing",
            description: build_description(alert_name, description, annotations),
            severity: SEVERITY_MAP.fetch(labels[:severity].to_s, 'medium'),
            status: auto_investigate ? 'investigating' : 'open',
            affected_service: affected_service,
            reporter_id: nil # system-generated
          }
        end

        def start_devin_session(incident, auto_investigate)
          unless auto_investigate
            Rails.logger.info("Auto-investigate disabled — skipping Devin session for incident #{incident.id}")
            return nil
          end

          session_result = DevinSessionService.create_session(incident: incident)
          incident.update!(Incident.devin_session_attributes(session_result)) if session_result
          session_result
        end

        def active_incident_for(affected_service)
          Incident.where(affected_service: affected_service)
                  .where(status: %w[open investigating])
                  .first
        end

        def resolve_incident(affected_service, alert_name)
          return if affected_service.blank?

          incident = active_incident_for(affected_service)
          return unless incident

          incident.resolve!
          Rails.logger.info("Incident #{incident.id} auto-resolved by Grafana alert #{alert_name}")
        rescue Incident::InvalidTransitionError => e
          Rails.logger.warn("Could not auto-resolve incident #{incident.id} for alert #{alert_name}: #{e.message}")
        end

        def build_description(alert_name, base_description, annotations)
          parts = [base_description]
          parts << "**Alert**: #{alert_name}" if alert_name.present?
          if (runbook = annotations[:runbook_url].to_s).present?
            parts << "**Runbook**: #{runbook}"
          end
          parts << '**Source**: Grafana Unified Alerting (auto-generated incident)'
          parts.join("\n\n")
        end

        def verify_alert_secret
          expected = ENV.fetch('ALERT_WEBHOOK_SECRET', nil)
          return if expected.nil? # not configured → allow (dev/test)

          # Accept either X-Alert-Secret header or Authorization: Bearer <secret>
          # (Grafana webhook contact points send the token as a Bearer header)
          provided = request.headers['X-Alert-Secret'].presence ||
                     request.headers['Authorization'].to_s.delete_prefix('Bearer ').presence
          return if provided == expected

          render json: { error: 'Unauthorized' }, status: :unauthorized
        end
      end
    end
  end
end
