require 'rails_helper'

RSpec.describe Api::V1::Admin::ChaosController do
  let(:redis) { instance_double(Redis, setex: 'OK', keys: [], del: 0) }

  before do
    allow(RedisConnection).to receive(:build).and_return(redis)
    allow(ChaosProbeService).to receive(:start)
  end

  around { |example| with_env('CHAOS_SECRET' => nil) { example.run } }

  describe 'POST #trigger' do
    it 'sets the chaos flag with a TTL and starts the probe' do
      post :trigger, params: { service: 'search-service', scenario: 'suggest_500' }
      expect(response).to have_http_status(:ok)
      expect(redis).to have_received(:setex).with('chaos:search-service:suggest_500', 600, '1')
      expect(ChaosProbeService).to have_received(:start)
        .with(service: 'search-service', redis_key: 'chaos:search-service:suggest_500')
    end

    it 'rejects an invalid service/scenario combination' do
      post :trigger, params: { service: 'search-service', scenario: 'slow_queries' }
      expect(response).to have_http_status(:unprocessable_content)
      expect(redis).not_to have_received(:setex)
    end

    context 'when CHAOS_SECRET is configured' do
      around { |example| with_env('CHAOS_SECRET' => 's3cret') { example.run } }

      it 'rejects a missing or wrong secret' do
        request.headers['X-Chaos-Secret'] = 'nope'
        post :trigger, params: { service: 'search-service', scenario: 'suggest_500' }
        expect(response).to have_http_status(:unauthorized)
      end

      it 'accepts the matching secret' do
        request.headers['X-Chaos-Secret'] = 's3cret'
        post :trigger, params: { service: 'search-service', scenario: 'suggest_500' }
        expect(response).to have_http_status(:ok)
      end
    end

    context 'when CHAOS_SECRET is empty' do
      around { |example| with_env('CHAOS_SECRET' => '') { example.run } }

      it 'allows the request' do
        post :trigger, params: { service: 'search-service', scenario: 'suggest_500' }
        expect(response).to have_http_status(:ok)
      end
    end
  end

  describe 'DELETE #reset' do
    it 'clears chaos flags and resolves open incidents for chaos services' do
      allow(redis).to receive(:keys).with('chaos:*').and_return(['chaos:search-service:suggest_500'])
      incident = create(:incident, affected_service: 'search-service')
      other = create(:incident, affected_service: 'auth-service')

      delete :reset
      expect(response).to have_http_status(:ok)
      expect(redis).to have_received(:del).with('chaos:search-service:suggest_500')
      expect(response.parsed_body['resolved_incidents']).to eq([incident.id])
      expect(incident.reload.status).to eq('resolved')
      expect(other.reload.status).to eq('open')
    end
  end
end
