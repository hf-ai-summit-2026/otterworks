require 'rails_helper'

RSpec.describe Api::V1::Admin::ChaosController do
  let(:redis) { instance_double(Redis) }
  let(:chaos_keys) { %w[chaos:search-service:suggest_500 chaos:file-service:upload_s3_error] }

  before do
    set_jwt_env(request)
    allow(controller).to receive(:redis).and_return(redis)
    allow(redis).to receive(:scan_each).with(match: 'chaos:*', count: 100).and_return(chaos_keys.each)
    allow(redis).to receive(:del)
  end

  describe 'DELETE #reset' do
    it 'clears chaos flags via SCAN instead of KEYS' do
      delete :reset

      expect(response).to have_http_status(:ok)
      expect(redis).to have_received(:del).with(*chaos_keys)
      expect(response.parsed_body['cleared']).to match_array(chaos_keys)
    end

    it 'resolves active incidents for chaos-managed services' do
      incident = create(:incident, affected_service: 'search-service')

      delete :reset

      expect(incident.reload.status).to eq('resolved')
      expect(response.parsed_body['resolved_incidents']).to eq([incident.id])
    end

    it 'skips DEL when no chaos flags exist' do
      allow(redis).to receive(:scan_each).and_return([].each)

      delete :reset

      expect(redis).not_to have_received(:del)
      expect(response.parsed_body['cleared']).to eq([])
    end
  end
end
