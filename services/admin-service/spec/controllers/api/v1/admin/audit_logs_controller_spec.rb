require 'rails_helper'

RSpec.describe Api::V1::Admin::AuditLogsController do
  before { set_jwt_env(request) }

  describe 'GET #index' do
    let!(:logs) { create_list(:audit_log, 3) }

    it 'returns paginated audit logs' do
      get :index
      expect(response).to have_http_status(:ok)
      body = JSON.parse(response.body)
      expect(body['audit_logs'].length).to eq(3)
    end

    it 'filters by action type' do
      create(:audit_log, action: 'feature_flag.created')
      get :index, params: { action_type: 'feature_flag.created' }
      body = JSON.parse(response.body)
      expect(body['audit_logs'].all? { |l| l['action'] == 'feature_flag.created' }).to be true
    end

    it 'filters by resource type' do
      get :index, params: { resource_type: 'AdminUser' }
      body = JSON.parse(response.body)
      expect(body['audit_logs'].all? { |l| l['resource_type'] == 'AdminUser' }).to be true
    end

    describe 'pagination' do
      it 'defaults to page 1 with 20 per page' do
        get :index
        body = JSON.parse(response.body)
        expect(body.slice('page', 'per_page', 'total')).to eq('page' => 1, 'per_page' => 20, 'total' => 3)
        expect(%w[X-Total-Count X-Page X-Per-Page].map { |h| response.headers[h] }).to eq(%w[3 1 20])
      end

      it 'returns the requested page' do
        get :index, params: { page: 2, per_page: 2 }
        body = JSON.parse(response.body)
        expect(body['audit_logs'].length).to eq(1)
        expect(body.slice('page', 'per_page')).to eq('page' => 2, 'per_page' => 2)
      end

      it 'caps per_page at 100' do
        get :index, params: { per_page: 500 }
        expect(JSON.parse(response.body)['per_page']).to eq(100)
      end

      it 'raises per_page below 1 to 1' do
        get :index, params: { per_page: 0 }
        expect(JSON.parse(response.body)['per_page']).to eq(1)
      end

      it 'treats a non-positive page as page 1' do
        get :index, params: { page: -3 }
        expect(JSON.parse(response.body)['page']).to eq(1)
      end
    end
  end

  describe 'GET #show' do
    let(:log) { create(:audit_log) }

    it 'returns the audit log entry' do
      get :show, params: { id: log.id }
      expect(response).to have_http_status(:ok)
      body = JSON.parse(response.body)
      expect(body['id']).to eq(log.id)
    end
  end
end
