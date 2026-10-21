module Api
  module V1
    module Admin
      class IncidentsController < ApplicationController
        before_action :set_incident, only: %i[show update destroy trigger_session]

        # GET /api/v1/admin/incidents
        def index
          scope = Incident.all
          scope = scope.by_status(params[:status]) if params[:status].present?
          scope = scope.by_severity(params[:severity]) if params[:severity].present?
          scope = scope.active if params[:active] == 'true'
          scope = scope.order(created_at: :desc)

          result = paginate(scope)

          render json: {
            incidents: ActiveModelSerializers::SerializableResource.new(result[:records]),
            total: result[:total],
            page: result[:page],
            per_page: result[:per_page]
          }
        end

        # GET /api/v1/admin/incidents/:id
        def show
          # Refresh Devin session status if session exists and incident is active
          if @incident.has_devin_session? && @incident.active?
            session_info = DevinSessionService.get_session(session_id: @incident.devin_session_id)
            @incident.sync_devin_session(session_info) if session_info
          end

          render json: @incident, serializer: IncidentSerializer
        end

        # POST /api/v1/admin/incidents
        def create
          incident = Incident.new(incident_params)
          incident.reporter_id = current_user_id
          incident.status = 'investigating'

          if incident.save
            # Trigger Devin session
            session_result = DevinSessionService.create_session(incident: incident)

            incident.update(Incident.devin_session_attributes(session_result)) if session_result

            audit('incident.created', incident.id,
                  incident.attributes.merge(devin_session_created: session_result.present?))

            render json: incident, serializer: IncidentSerializer, status: :created
          else
            render json: { error: 'Validation failed', details: incident.errors.full_messages },
                   status: :unprocessable_content
          end
        end

        # PATCH/PUT /api/v1/admin/incidents/:id
        def update
          new_status = status_params[:status]

          unless @incident.can_transition_to?(new_status)
            return render json: {
              error: 'Invalid status transition',
              details: "Cannot transition from '#{@incident.status}' to '#{new_status}'"
            }, status: :unprocessable_content
          end

          previous_status = @incident.status

          apply_transition!(new_status)

          audit("incident.#{new_status}", @incident.id, { previous_status: previous_status, new_status: new_status })

          render json: @incident, serializer: IncidentSerializer
        rescue Incident::InvalidTransitionError => e
          render json: { error: 'Invalid status transition', details: e.message },
                 status: :unprocessable_content
        end

        # DELETE /api/v1/admin/incidents/:id
        def destroy
          if @incident.has_active_devin_session?
            return render json: {
              error: 'Cannot delete incident with an active Devin session',
              details: "Stop Devin session '#{@incident.devin_session_id}' before deleting"
            }, status: :conflict
          end

          incident_attrs = @incident.attributes

          @incident.destroy!

          audit('incident.deleted', incident_attrs['id'], incident_attrs)

          head :no_content
        end

        # POST /api/v1/admin/incidents/:id/trigger_session
        def trigger_session
          if @incident.devin_session_id.present?
            return render json: { error: 'Incident already has a Devin session' }, status: :unprocessable_content
          end

          session_result = DevinSessionService.create_session(incident: @incident)

          if session_result
            @incident.update(Incident.devin_session_attributes(session_result))
            render json: @incident, serializer: IncidentSerializer
          else
            render json: { error: 'Failed to create Devin session' }, status: :service_unavailable
          end
        end

        private

        def audit(action, resource_id, changes)
          AuditLogger.log(action: action, resource_type: 'Incident', resource_id: resource_id,
                          request: request, changes_made: changes)
        end

        def apply_transition!(new_status)
          case new_status
          when 'resolved' then @incident.resolve!
          when 'closed' then @incident.close!
          when 'investigating' then @incident.investigate!
          end
        end

        def set_incident
          @incident = Incident.find(params[:id]) # nosemgrep: ruby.rails.security.brakeman.check-unscoped-find.check-unscoped-find
        end

        def incident_params
          params.require(:incident).permit(:title, :description, :severity, :affected_service)
        end

        def status_params
          params.require(:incident).permit(:status)
        end
      end
    end
  end
end
