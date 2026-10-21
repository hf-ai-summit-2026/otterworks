require 'rails_helper'

RSpec.describe Api::V1::Admin::AlertsController do
  let(:auto_investigate) { false }
  let(:session_result) { { session_id: 'sess-1', url: 'https://app.devin.ai/sessions/sess-1' } }

  def alert(status: 'firing', service: 'search-service', severity: 'critical', **extra)
    {
      status: status,
      labels: { alertname: 'HighErrorRate', severity: severity, affected_service: service },
      annotations: { summary: 'Search 5xx spike', description: 'Error rate > 5%', runbook_url: 'https://runbook' }
    }.deep_merge(extra)
  end

  def ingest(*alerts)
    post :ingest, params: { alerts: alerts }, as: :json
  end

  before do
    allow(AdminSettingsService).to receive(:auto_investigate_enabled?).and_return(auto_investigate)
    allow(DevinSessionService).to receive(:create_session).and_return(session_result)
  end

  around { |example| with_env('ALERT_WEBHOOK_SECRET' => nil) { example.run } }

  it 'rejects payloads without an alerts array' do
    post :ingest, params: { receiver: 'x' }, as: :json
    expect(response).to have_http_status(:bad_request)
  end

  context 'with a firing alert and auto-investigate disabled' do
    it 'creates an open incident without a Devin session' do
      expect { ingest(alert) }.to change(Incident, :count).by(1)

      incident = Incident.last
      expect(response.parsed_body).to include('received' => 1, 'processed' => 1)
      expect(incident).to have_attributes(
        title: 'Search 5xx spike', severity: 'critical', status: 'open',
        affected_service: 'search-service', devin_session_id: nil
      )
      expect(incident.description).to include('Error rate > 5%', '**Alert**: HighErrorRate',
                                              '**Runbook**: https://runbook')
      expect(DevinSessionService).not_to have_received(:create_session)
    end
  end

  context 'with a firing alert and auto-investigate enabled' do
    let(:auto_investigate) { true }

    it 'creates an investigating incident and attaches the Devin session' do
      ingest(alert(severity: 'warning'))

      incident = Incident.last
      expect(incident).to have_attributes(
        status: 'investigating', severity: 'medium', devin_session_id: 'sess-1',
        devin_session_url: 'https://app.devin.ai/sessions/sess-1', devin_session_status: 'running'
      )
      expect(response.parsed_body['incidents'].first).to include('devin_session' => true)
    end
  end

  it 'skips duplicates while an incident is active for the service' do
    existing = create(:incident, affected_service: 'search-service')

    expect { ingest(alert) }.not_to change(Incident, :count)
    expect(response.parsed_body['incidents'].first)
      .to eq('skipped' => true, 'incident_id' => existing.id, 'reason' => 'duplicate')
  end

  it 'ignores firing alerts without an affected service' do
    expect { ingest(alert(service: '')) }.not_to change(Incident, :count)
    expect(response.parsed_body).to include('received' => 1, 'processed' => 0)
  end

  it 'resolves the active incident when the alert resolves' do
    incident = create(:incident, affected_service: 'search-service')

    ingest(alert(status: 'resolved'))
    expect(incident.reload.status).to eq('resolved')
    expect(response.parsed_body).to include('processed' => 0)
  end

  context 'when ALERT_WEBHOOK_SECRET is configured' do
    around { |example| with_env('ALERT_WEBHOOK_SECRET' => 'hook') { example.run } }

    it 'rejects requests without the secret' do
      ingest(alert)
      expect(response).to have_http_status(:unauthorized)
    end

    it 'accepts the secret as a Bearer token' do
      request.headers['Authorization'] = 'Bearer hook'
      ingest(alert)
      expect(response).to have_http_status(:ok)
    end
  end
end
