from time import time, sleep

from algosdk import account, encoding
from algosdk.logic import get_application_address
from amm.operations import createAmmApp, setupAmmApp, supply, withdraw, trade
from amm.util import (
    getBalances,
    getAppGlobalState,
    getLastBlockTimestamp,
)
from amm.testing.setup import getAlgodClient
from amm.testing.resources import (
    getTemporaryAccount,
    optInToAsset,
    createDummyAsset,
)


def simple_auction():
    client = getAlgodClient()

    print("Alice is generating temporary accounts...")
    creator = getTemporaryAccount(client)
    supplier = getTemporaryAccount(client)

    print("Alice is generating example tokens...")
    tokenAAmount = 10 ** 13
    tokenBAmount = 10 ** 13
    tokenA = createDummyAsset(client, tokenBAmount, creator)
    tokenB = createDummyAsset(client, tokenBAmount, creator)
    poolToken = createDummyAsset(client, tokenAAmount, creator)
    print("TokenA id is:", tokenA)
    print("TokenB id is:", tokenB)
    print("Pool token id is:", poolToken)

    print(
        "Alice is creating AMM that swaps between token A and token B..."
    )
    appID = createAmmApp(client=client, sender=creator, tokenA=tokenA, tokenB=tokenB, poolToken=poolToken, feeBps=30, minIncrement=1000)

    print("Alice is setting up and funding amm...")
    setupAmmApp(
        client=client,
        appID=appID,
        funder=creator,
        tokenA=tokenA,
        tokenB=tokenB,
        poolToken=poolToken,
        poolTokenQty=tokenAAmount,
    )

    creatorBalancesBefore = getBalances(client, creator.getAddress())
    ammBalancesBefore = getBalances(client, get_application_address(appID))

    print("Alice's balances: ", creatorBalancesBefore)
    print("AMM's balances: ", ammBalancesBefore)

    print("Supplying AMM with initial token A and token B")
    supply(client=client, appID=appID, qA=500_000, qB=100_000_000, supplier=creator)
    ammBalancesSupplied = getBalances(client, get_application_address(appID))
    creatorBalancesSupplied = getBalances(client, creator.getAddress())
    poolTokenFirstAmount = creatorBalancesSupplied[poolToken]
    print("AMM's balances: ", ammBalancesSupplied)
    print("Alice's balances: ", creatorBalancesSupplied)

    print("Supplying AMM with same token A and token B")
    supply(client=client, appID=appID, qA=100_000, qB=20_000_000, supplier=creator)
    ammBalancesSupplied = getBalances(client, get_application_address(appID))
    creatorBalancesSupplied = getBalances(client, creator.getAddress())

    print("AMM's balances: ", ammBalancesSupplied)
    print("Alice's balances: ", creatorBalancesSupplied)

    print("Supplying AMM with too large ratio of token A and token B")
    supply(client=client, appID=appID, qA=100_000, qB=100_000, supplier=creator)
    ammBalancesSupplied = getBalances(client, get_application_address(appID))
    creatorBalancesSupplied = getBalances(client, creator.getAddress())
    print("AMM's balances: ", ammBalancesSupplied)
    print("Alice's balances: ", creatorBalancesSupplied)

    print("Supplying AMM with too small ratio of token A and token B")
    supply(client=client, appID=appID, qA=100_000, qB=100_000_000, supplier=creator)
    ammBalancesSupplied = getBalances(client, get_application_address(appID))
    creatorBalancesSupplied = getBalances(client, creator.getAddress())

    print("AMM's balances: ", ammBalancesSupplied)
    print("Alice's balances: ", creatorBalancesSupplied)
    poolTokenTotalAmount = creatorBalancesSupplied[poolToken]
    print(' ')
    print("Alice is exchanging her Token A for Token B")
    trade(client=client, appID=appID, tokenId=tokenA, amount=1_000, trader=creator)
    ammBalancesTraded= getBalances(client, get_application_address(appID))
    creatorBalancesTraded = getBalances(client, creator.getAddress())
    print("AMM's balances: ", ammBalancesTraded)
    print("Alice's balances: ", creatorBalancesTraded)

    print("Alice is exchanging her Token B for Token A")
    trade(client=client, appID=appID, tokenId=tokenB, amount=int(1_000_000 * 1.003), trader=creator)
    ammBalancesTraded= getBalances(client, get_application_address(appID))
    creatorBalancesTraded = getBalances(client, creator.getAddress())
    print("AMM's balances: ", ammBalancesTraded)
    print("Alice's balances: ", creatorBalancesTraded)
    print(' ')

    print("Withdrawing first supplied liquidity from AMM")
    print("Withdrawing: ", poolTokenFirstAmount)
    withdraw(client=client, appID=appID, poolTokenAmount=poolTokenFirstAmount, withdrawAccount=creator)
    ammBalancesWithdrawn = getBalances(client, get_application_address(appID))
    print("AMM's balances: ", ammBalancesWithdrawn)

    print("Withdrawing remainder of the supplied liquidity from AMM")
    poolTokenTotalAmount -= poolTokenFirstAmount
    withdraw(client=client, appID=appID, poolTokenAmount=poolTokenTotalAmount, withdrawAccount=creator)
    ammBalancesWithdrawn = getBalances(client, get_application_address(appID))
    print("AMM's balances: ", ammBalancesWithdrawn)

# bidder = getTemporaryAccount(client)
    #
    # _, lastRoundTime = getLastBlockTimestamp(client)
    # if lastRoundTime < startTime + 5:
    #     sleep(startTime + 5 - lastRoundTime)
    # actualAppBalancesBefore = getBalances(client, get_application_address(appID))
    # print("The smart contract now holds the following:", actualAppBalancesBefore)
    # bidAmount = reserve
    # bidderAlgosBefore = getBalances(client, bidder.getAddress())[0]
    # print("Carla wants to bid on NFT, her algo balance: ", bidderAlgosBefore, " algos")
    # print("Carla is placing bid for: ", bidAmount, " algos")
    #
    # placeBid(client=client, appID=appID, bidder=bidder, bidAmount=bidAmount)
    #
    # print("Carla is opting into NFT with id:", nftID)
    #
    # optInToAsset(client, nftID, bidder)
    #
    # _, lastRoundTime = getLastBlockTimestamp(client)
    # if lastRoundTime < endTime + 5:
    #     sleep(endTime + 5 - lastRoundTime)
    #
    # print("Alice is closing out the auction....")
    # closeAuction(client, appID, seller)
    #
    # actualAppBalances = getBalances(client, get_application_address(appID))
    # expectedAppBalances = {0: 0}
    # print("The smart contract now holds the following:", actualAppBalances)
    # assert actualAppBalances == expectedAppBalances
    #
    # bidderNftBalance = getBalances(client, bidder.getAddress())[nftID]
    #
    # print("Carla's NFT balance:", bidderNftBalance, " for NFT ID: ", nftID)
    #
    # assert bidderNftBalance == nftAmount
    #
    # actualSellerBalances = getBalances(client, seller.getAddress())
    # print("Alice's balances after auction: ", actualSellerBalances, " Algos")
    # actualBidderBalances = getBalances(client, bidder.getAddress())
    # print("Carla's balances after auction: ", actualBidderBalances, " Algos")
    # assert len(actualSellerBalances) == 2
    # # seller should receive the bid amount, minus the txn fee
    # assert actualSellerBalances[0] >= sellerAlgosBefore + bidAmount - 1_000
    # assert actualSellerBalances[nftID] == 0


simple_auction()
