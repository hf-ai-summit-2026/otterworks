require 'rails_helper'

RSpec.describe Api::V1::Admin::IncidentsController do
  let(:session_result) { { session_id: 'sess-1', url: 'https://app.devin.ai/sessions/sess-1' } }

  before do
    set_jwt_env(request)
    allow(DevinSessionService).to receive_messages(create_session: session_result, get_session: nil)
  end

  describe 'POST #create' do
    let(:params) do
      { incident: { title: 'Outage', description: 'Down', severity: 'high', affected_service: 'file-service' } }
    end

    it 'creates an investigating incident with the Devin session attached' do
      expect { post :create, params: params }.to change(Incident, :count).by(1)
      expect(response).to have_http_status(:created)
      expect(Incident.last).to have_attributes(status: 'investigating', devin_session_id: 'sess-1',
                                               devin_session_status: 'running')
    end

    it 'creates the incident without a session when Devin is unavailable' do
      allow(DevinSessionService).to receive(:create_session).and_return(nil)
      post :create, params: params
      expect(response).to have_http_status(:created)
      expect(Incident.last.devin_session_id).to be_nil
    end

    it 'returns 422 for invalid input' do
      post :create, params: { incident: { title: '' } }
      expect(response).to have_http_status(:unprocessable_content)
    end
  end

  describe 'PUT #update' do
    let(:incident) { create(:incident) }

    it 'applies a valid transition' do
      put :update, params: { id: incident.id, incident: { status: 'resolved' } }
      expect(response).to have_http_status(:ok)
      expect(incident.reload).to have_attributes(status: 'resolved', resolved_at: be_present)
    end

    it 'moves an open incident to investigating' do
      put :update, params: { id: incident.id, incident: { status: 'investigating' } }
      expect(incident.reload.status).to eq('investigating')
    end

    it 'closes a resolved incident' do
      resolved = create(:incident, :resolved)
      put :update, params: { id: resolved.id, incident: { status: 'closed' } }
      expect(resolved.reload).to have_attributes(status: 'closed', closed_at: be_present)
    end

    it 'rejects an invalid transition' do
      put :update, params: { id: incident.id, incident: { status: 'closed' } }
      expect(response).to have_http_status(:unprocessable_content)
      expect(incident.reload.status).to eq('open')
    end
  end

  describe 'GET #show' do
    it 'refreshes the Devin session status for an active incident' do
      incident = create(:incident, :with_running_session)
      allow(DevinSessionService).to receive(:get_session).and_return({ status: 'finished', url: nil })

      get :show, params: { id: incident.id }
      expect(response).to have_http_status(:ok)
      expect(incident.reload).to have_attributes(devin_session_status: 'finished',
                                                 devin_session_url: 'https://app.devin.ai/sessions/example')
    end

    it 'does not query Devin for incidents without a session' do
      incident = create(:incident)
      get :show, params: { id: incident.id }
      expect(DevinSessionService).not_to have_received(:get_session)
    end
  end

  describe 'audit logging' do
    it 'records the transition' do
      allow(AuditLogger).to receive(:log)
      incident = create(:incident)
      put :update, params: { id: incident.id, incident: { status: 'resolved' } }
      expect(AuditLogger).to have_received(:log).with(
        hash_including(action: 'incident.resolved', resource_type: 'Incident', resource_id: incident.id,
                       changes_made: { previous_status: 'open', new_status: 'resolved' })
      )
    end
  end

  describe 'DELETE #destroy' do
    it 'refuses to delete an incident with a running Devin session' do
      incident = create(:incident, :with_running_session)
      delete :destroy, params: { id: incident.id }
      expect(response).to have_http_status(:conflict)
    end

    it 'deletes an incident without an active session' do
      incident = create(:incident)
      delete :destroy, params: { id: incident.id }
      expect(response).to have_http_status(:no_content)
      expect(Incident.exists?(incident.id)).to be(false)
    end
  end

  describe 'POST #trigger_session' do
    it 'attaches a new Devin session' do
      incident = create(:incident)
      post :trigger_session, params: { id: incident.id }
      expect(response).to have_http_status(:ok)
      expect(incident.reload.devin_session_id).to eq('sess-1')
    end

    it 'rejects incidents that already have a session' do
      incident = create(:incident, :with_running_session)
      post :trigger_session, params: { id: incident.id }
      expect(response).to have_http_status(:unprocessable_content)
    end

    it 'returns 503 when the session cannot be created' do
      allow(DevinSessionService).to receive(:create_session).and_return(nil)
      incident = create(:incident)
      post :trigger_session, params: { id: incident.id }
      expect(response).to have_http_status(:service_unavailable)
    end
  end
end
